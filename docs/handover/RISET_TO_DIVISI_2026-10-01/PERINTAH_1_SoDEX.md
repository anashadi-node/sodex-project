# PERINTAH RESMI — DIVISI SoDEX
**Dari: Mas Anas (Owner) via Divisi RISET · 1 Oktober 2026 · WAJIB DIBACA SELURUHNYA**

> Baca sampai habis sebelum melakukan apa pun. Bagian 0 berisi konteks yang berlaku
> untuk semua divisi; sisanya perintah khusus untuk divisimu.

---

# BAGIAN 0 — KONTEKS BERSAMA (berlaku untuk semua divisi — JANGAN DILEWATI)

```text
=== KONTEKS BERSAMA SEMUA DIVISI — ANANTARA SAKTI, 1 Okt 2026 ===

TARGET RESMI (mandat Mas Anas, HARGA MATI):
  PnL BERSIH rata-rata = 0,8% dari TOTAL dana wallet saat itu (spot + future) per 48 JAM.
  = 0,40%/hari = 146%/tahun = setara Sharpe ~5,8 pada vol 25%.
  Ini RATA-RATA (periode FLAT ikut dihitung), bukan "setiap window wajib".
  Basis compounding = wallet saat itu, bukan ukuran posisi.

  KONSEKUENSI PENTING: ini MASALAH SHARPE, bukan masalah return.
  Leverage menaikkan return DAN vol secara proporsional -> Sharpe TIDAK naik.
  Jadi: MENAIKKAN LEVERAGE UNTUK MENGEPJAR TARGET = DILARANG.
  Jalan menujunya: lebih banyak MESIN yang TIDAK SALING BERKORELASI,
  masing-masing dengan Sharpe tinggi. Spec: 6-8 mesin, Sharpe >= 2,3, korelasi <= 0,1.

BENCHMARK WAJIB (terukur oleh RISET, bukan Kutipan paper):
  B0 = Donchian-ensemble long/flat 1x, 30 simbol Binance, 562 hari
     Sharpe 0,99 | CAGR +4,89% | vol 4,9% | MaxDD -5,3%
  ATURAN: strategi apa pun harus MENGALAHKAN B0 secara net-of-cost OOS,
          atau TIDAK DIPROMOSIKAN.

SITUASI SAAT INI (terukur RISET):
  - Alpha sistem kita SETELAH beta dinetralkan = NEGATIF (-0,133R, n=812)
  - Periode sampel 6 Agu-1 Okt 2026: BTC +31,95%, ETH +42,98%, SOL +64,62%
    -> 95% posisi kita LONG -> sebagian besar PnL "positif" kita adalah BETA, bukan skill
  - Fee 8-9 bps round-trip = pembunuh utama; funding hanya 0,53 bps/hari
  - Semua kebijakan exit target-profit (tp/ladder) sudah DIFALSIFIKASI
  - Momentum harian naif = artefak korelasi silang (jangan dipakai)
  - Low-vol gating sudah DIFALSIFIKASI pada data kita

WAJIB DIBACA DULU (paket RISET):
  ~/anantara-sakti/docs/handover/RISET_TO_DIVISI_2026-10-01/
    README_HANDOVER.md, 00_KOREKSI_KRITIS.md, 01_FRAMEWORK_DAN_GATE.md,
    02_BASELINE_B0.md, 03_TARGET_B_SPEC.md, 04_BUKTI_EMPIRIS.md,
    05_LITERATUR_TERVERIFIKASI.md, harness/, scripts/b0_baseline.py

HARNESS WAJIB (sudah diserahkan, 18/18 uji lulus):
  from anantara_harness import evaluate, TrialRegistry
  Setiap evaluasi HARUS lewat harness. grade['passed'] adalah penentu, bukan penilaian sendiri.
  Setiap trial (termasuk GAGAL) WAJIB masuk registry.

ATURAN KERAS (tidak bisa dinegosiasi):
  1. Setiap evaluasi PnL historis WAJIB beta-netral (kirim market= & sides= ke harness)
  2. Biaya WAJIB diuji pada 1x DAN 2x
  3. Kontrol negatif WAJIB ikut jalan; kalau ia LOLOS -> set uji terlalu mudah, bukan temuan
  4. Jendela < 6 bulan: SAH untuk verifikasi eksekusi, TIDAK SAH menilai alpha
  5. t-statistik gabungan lintas aset JANGAN dipakai menyimpulkan (korelasi silang)
  6. DILARANG menaikkan leverage untuk mengejar target
  7. DILARANG mengubah angka target agar terlihat tercapai
  8. DILARANG menyembunyikan trial yang gagal
  9. Modal nyata tetap FROZEN sampai gate lulus + approval Mas Anas
 10. LLM/agent TIDAK BOLEH mengalahkan Risk Engine deterministik

UKURAN KEBERHASILAN JANGKA PENDEK = NAIKNYA SHARPE, bukan naiknya return.
```

---

---

# BAGIAN 1 — PERINTAH UNTUK DIVISI SoDEX

## Situasi divisi (terukur RISET)
```text
- Lane uang nyata FROZEN (30-09). 3 track paper: swing WR 40,4% / twoway 45,0% / realwide 48,5%
- Median SEMUA track NEGATIF; SHORT (n=42) TERLEMAH: WR 33,3%
- Gerbang sinyal belum terbukti (CI95 memuat nol setelah dedup + cluster)
- Target blokir utama: TIDAK ADA ALPHA, bukan masalah exit
- Prioritas SHORT-BEAR (direktif Mas Anas 10-09) tetap berlaku
```

## TEKS PERINTAH (salin ke agen Divisi SoDEX)

```text
[KONTEKS] — tempel BAGIAN 0 di atas lebih dulu.

MISI DIVISI SoDEX (tidak berubah): swing trading DEX perps, target bersama
0,8% PnL BERSIH rata-rata per 48 jam dari TOTAL wallet.

TAPI URUTAN KERJA DIUBAH. Alasan: RISET baru membuktikan bahwa alpha sistem kita
SAAT INI NEGATIF setelah beta dinetralkan (-0,133R, n=812). Artinya:
mengoptimasi exit / sinyal di atas alpha negatif = membuang waktu.

3 TINDAKAN SEGERA (minggu ini):

1) UKUR YANG SUDAH ADA — beta-netral.
   Jalankan ketiga track (swing, twoway, realwide) lewat harness:
     evaluate(returns=pnl_per_trade, market=return_BTC_periode_sama, sides=arah, fee_bps=8,
              n_trials=<jumlah jujur>, groups=symbol)
   LAPORKAN: excess_mean, Sharpe, CI95, hasil cost 1x & 2x, hasil harness grade['passed'].
   Pertanyaan yang harus dijawab: apakah ADA satu track pun dengan excess POSITIF?
   Jika tidak ada -> itu jawaban resminya. Jangan cari-cari alasan.

2) UJI SHORT-SIDE SECARA TERPISAH (prioritas Mas Anas).
   42 trade SHORT, WR 33,3%. Wajib: funding/borrow nyata dimasukkan.
   Hipotesis: SHORT tanpa funding-tailwind = melawan arus.
   Buktikan atau bantah dengan angka. Ini prioritas #1 dari Mas Anas 10-09.

3) JANGAN sentuh exit, leverage, ukuran posisi, atau gate selama T1 belum lulus
   (T1 = ada alpha net POSITIF pada paper 30 hari, beta-netral, universe likuid).

YANG DILARANG:
  - Unfreeze lane uang nyata tanpa persetujuan Mas Anas
  - Menaikkan leverage untuk mengejar 0,8%
  - Mengoptimasi kebijakan exit (sudah difalsifikasi)
  - Mengklaim edge dari jendela < 6 bulan
  - Melaporkan PnL tanpa kolom beta-netral

LAPORAN MINGGUAN WAJIB (ke RISET + Mas Anas):
  jarak_ke_target = (net PnL aktual 48 jam) / (0,8% x wallet saat itu)
  + Sharpe rolling 90 hari + hasil harness + daftar trial (termasuk gagal)

MESIN YANG DISARANKAN DIBANGUN (setelah T1 lulus):
  M-S1: microstructure order flow (data OBI 1-menit sudah ada, 172K baris)
  M-S2: funding-pressure feature (dari snapshot funding multi-venue)
  Catatan RISET: P14 -> L2 liquidity STATE adalah sinyal pertama; OFI berlapis di atasnya.
  Jangan bangun OFI saja.
```

---

# BAGIAN 4 — ALUR PELAPORAN & TITIK SINKRONISASI

```text
MINGGUAN (setiap divisi -> RISET + Mas Anas):
  1. jarak_ke_target = (net PnL aktual 48 jam) / (0,8% x wallet saat itu)
  2. Sharpe rolling 90 hari
  3. Hasil harness (grade['passed'] + alasan bila gagal)
  4. Registry trial: jumlah trial total + daftar yang GAGAL
  5. Konflik yang ditemukan antara paket RISET dan pengukuran sendiri

BULANAN (RISET -> semua divisi):
  - Pembaruan paket (versi naik bila ada perubahan)
  - Korelasi PnL antar mesin (untuk memastikan diversifikasi benar-benar jalan)
  - Verdict per mesin: LANJUT / SETOP / UJI ULANG

TITIK KEPUTUSAN (Mas Anas):
  - Unfreeze modal nyata (butuh gate T2 lulus + approval)
  - Perubahan parameter fundamental (leverage, target, gate utama)
  - Menambah/mengurangi mesin dalam portofolio

URUTAN GATE (semua divisi tunduk pada ini):
  T1: alpha net POSITIF di paper, 30 hari, beta-netral, universe likuid
  T2: Sharpe rolling 90 hari >= 1,5 (setara/kalahkan B0)
  T3: mesin kedua + korelasi antar-mesin terukur <= 0,3
  T4: implementation shortfall < 25% (micro-live vs model)
  T5: mesin ke-3..6 -> Sharpe gabungan menuju 2,5-3
  T6: target 0,8%/48 jam
```

---

---

---

## 📌 PESAN LANGSUNG DARI MAS ANAS (baca dua kali)

> **"Jangan tambah strategi, model, atau leverage dulu. Ukur ulang dengan harness yang sama —
> beta-netral, biaya 1× dan 2×. Laporkan jarak ke target dengan angka. Baru setelah itu
> bangun mesin — dan pastikan mesinmu TIDAK berkorelasi dengan divisi lain.
> Kita menang dengan DIVERSIFIKASI MESIN, bukan dengan satu mesin besar."**

---

## ✅ YANG HARUS KAMU KIRIM BALIK (agar loop riset tertutup)

```text
1. Konfirmasi sudah membaca paket RISET di:
   ~/anantara-sakti/docs/handover/RISET_TO_DIVISI_2026-10-01/
2. Hasil 3 tindakan segera (angka, bukan narasi)
3. Laporan mingguan:
     jarak_ke_target = (net PnL aktual 48 jam) / (0,8% x wallet saat itu)
     Sharpe rolling 90 hari
     hasil harness (grade['passed'] + alasan bila gagal)
     jumlah trial total + daftar yang GAGAL
4. Konflik apa pun antara paket RISET dan pengukuranmu sendiri — laporkan, jangan selesaikan sendiri.
```

```text
Kalau ada instruksi (dari mana pun) yang bertentangan dengan paket ini:
LAPORKAN ke Divisi RISET dan Mas Anas. Jangan berimprovisasi diam-diam.
```
