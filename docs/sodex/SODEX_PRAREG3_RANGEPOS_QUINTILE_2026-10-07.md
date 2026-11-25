# SODEX PRAREG-3 — RANGEPOS KUINTIL (momentum ekor) — PRA-REGISTRASI BEKU — 2026-10-07

**Status: BEKU. Ditetapkan sebelum satu pun angka kuintil-nya dihitung sebagai uji.**
Amendemen hanya boleh **MEMPERKETAT**.
Registry trial ekosistem: 41.

---

## 0. Deklarasi jujur tentang apa yang sudah terlihat (WAJIB dibaca lebih dulu)

Ini bagian terpenting dari dokumen ini. Saya menulisnya apa adanya:

1. `RANGEPOS` sebagai **reversal** sudah **ditolak kuat** (PRAREG-1, Binance: t=−5,10, 3/3 segmen negatif).
2. Tanda **momentum** dipilih **setelah** melihat data itu → sudah diuji sah di PRAREG-2
   (`range_pos_validation.py`) dengan pemisahan waktu, hasil **TIDAK LULUS** (S_ann OOS 1,75 < 2,30)
   tetapi t=2,80, p=0,0052, 3/3 segmen positif, kontrol gagal.
3. Saat memeriksa kontradiksi IC (−0,0179) vs netto (+14,43 bps), saya menghitung
   **spread kuintil** pada OOS Binance yang **sudah terpakai**: +53,72 bps, t=+4,19.
4. Saya juga sudah menghitung spread kuintil pada **seluruh** panel SoDEX 1d dan 1h
   (tanpa pemisahan waktu): SoDEX 1d +39,48 bps (t=1,65), SoDEX 1h −32,33 bps (t=−2,30).

**Konsekuensi yang tidak boleh saya sembunyikan:** tidak ada lagi jendela historis yang
**murni bersih** untuk RANGEPOS. Binance sudah habis dipakai (IS+OOS PRAREG-2); SoDEX 1d
sudah dilihat agregatnya. Karena itu:

- Angka kuintil pada data historis di bawah ini sah dilaporkan **hanya sebagai DESKRIPTIF**,
  **tidak sah** sebagai verdict lulus/gagal.
- **Yang sah untuk verdict hanyalah data FORWARD** yang belum ada saat dokumen ini ditulis.

## 1. Hipotesis (satu, terkunci)

`RANGEPOS` ekor = momentum harian. Konstruksi **kuintil/desil** (long kuintil teratas,
short kuintil terbawah dari posisi rentang 20 hari), dollar-neutral, bobot sama per nama.

Alasan konstruksi ini (dari diagnostik, bukan dari harapan): hubungan rentang-posisi ↔
imbal hasil **non-monoton** — efek kuat di ekor (+53,72 bps) tetapi IC peringkat sedikit
negatif (−0,0179). Bobot peringkat merata hanya menangkap 27% dari efek ekor. Kuintil
memusatkan bobot di ekor.

## 2. Spesifikasi BEKU

```
sinyal   : S = (close − lo(20)) / (hi(20) − lo(20))          N = 20
portofolio:
   utama  = KUINTIL  : long 20% teratas S, short 20% terbawah S, bobot sama, dollar-neutral
   pembanding = DESIL: long 10% teratas, short 10% terbawah
hold     : 1 hari (utama) dan 2 hari (pembanding)   [bar harian]
biaya    : 1×   = 8,00 bps round-trip   (taker SoDEX resmi 4 bps/sisi)
           real = 9,71 bps round-trip   (+ slippage 0,86 bps/sisi)
           2×   = 16,00 bps round-trip
turnover : DIUKUR, tidak diasumsikan (konstruksi kuintil ≠ konstruksi peringkat)
kontrol  : (a) tanda sinyal diacak dalam baris, konstruksi kuintil identik
           (b) portofolio kuintil dari sinyal acak murni (tanpa sinyal)
           Kontrol dinilai pada BRUTO (netto kontrol tercemar biaya turnover acak).
```

**Keluarga hipotesis (BEKU, kecil supaya tidak p-hacking):** 4 sel
= {kuintil, desil} × {hold 1 hari, hold 2 hari}. BH-FDR q=0,10 atas 4 sel itu.
N=20 tetap apa pun hasilnya; N ∈ {10, 40, 60} dilaporkan **hanya sebagai stabilitas**.

## 3. Gerbang keputusan (BEKU)

| # | Syarat |
|---|---|
| g1 | jumlah periode ≥ **203** (n yang dibutuhkan agar t mencapai 2,0 pada besaran yang teramati di SoDEX 1d: 138 × (2,0/1,65)² ≈ 203) **dan** ≥ 60 hari |
| g2 | spread netto > 0 pada biaya **1×** (8 bps) |
| g3 | spread netto > 0 pada biaya **2×** (16 bps) |
| g4 | t_NW ≥ 2,0 (Newey-West, lag = hold) |
| g5 | 3/3 segmen waktu positif |
| g6 | kontrol negatif (a) dan (b) **tidak lulus** |
| g7 | tanda **konsisten** dengan Binance (garis dasar: momentum) |

Lolos semua = kandidat mesin, dilanjutkan ke uji korelasi antar-divisi. **BUKAN** berarti
target 0,8%/48 jam tercapai.

## 4. Aritmetika daya — dan peringatan tentang tenggat (jujur)

| | Nilai |
|---|---:|
| Periode SoDEX 1d tersedia sekarang (historis) | 138 (hold 2 hari) / 361 (hold 1 hari) |
| Periode forward 07-Okt → HARD_STOP 20-Nov (44 hari) | **≈ 44 (hold 1 hari) / 22 (hold 2 hari)** |
| Periode yang dibutuhkan untuk t=2,0 | ≈ **203** |

**Kesimpulan yang harus disampaikan tanpa diperhalus:** pada horizon harian, **sertifikasi
penuh tidak mungkin dicapai sebelum 20-Nov** hanya dari data forward. Karena jendela
historis sudah terpakai untuk pemilihan hipotesis, tidak ada jalan pintas statistik yang sah.

Artinya: kalau target 0,8%/48 jam hanya bisa dicapai lewat mekanisme horizon harian, maka
**tenggat 20-Nov tidak bisa dipenuhi dengan bukti kelas-sertifikasi** — dan saya lebih memilih
mengatakan itu sekarang daripada menyerahkan "lulus" yang tidak bisa saya pertahankan.

Karena itu PRAREG-3 dipakai untuk **menaikkan daya**, bukan menunggu:
- hold **1 hari** (bukan 2) → periode 2× lebih banyak,
- sebaran ekor (kuintil/desil) → t lebih tinggi pada n sama,
- **memperluas cakupan collector** (tape menit kita hanya 3 simbol sementara klines venue
  punya 76+ nama) sehingga n per periode naik.

## 5. Yang TIDAK dilakukan

- Tidak menjalankan versi kuintil pada data historis lalu menyebutnya lulus.
- Tidak menyetel ulang N, hold, atau ambang setelah melihat hasil.
- Tidak menghapus trial yang gagal dari registry.
- Tidak mengubah target 0,8%/48 jam dan tidak menaikkan leverage.
- Tidak mengklaim alpha dari jendela < 6 bulan (aturan #4 PERINTAH_1).

## 6. Berkas yang akan dibuat

- `scripts/research/rangepos_quintile_validation.py` — uji kuintil + kontrol (a)/(b)
- `reports/sodex/VALIDASI_RANGEPOS_KUINTIL.json` — hasil
- `docs/sodex/VALIDASI_RANGEPOS_KUINTIL_HASIL_*.md` — laporan (deskriptif vs forward dipisah tegas)

— BEKU. Hermes Anantara v3 — 2026-10-07
