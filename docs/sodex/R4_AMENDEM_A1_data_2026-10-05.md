# R4 — AMENDEM A1: hasil unduh data (ketersediaan nyata)

**Tanggal**: 05 Oktober 2026 (SESUDAH protokol dibekukan, SEBELUM evaluasi apa pun)
**Jenis perubahan**: catatan ketersediaan data — **BUKAN** pelonggaran ambang/hipotesis.
Ambang (§5), universe (§2), pemecahan DEV/LOCKBOX (§3), dan daftar hipotesis (§4) **tidak diubah**.

## 1. Hasil unduh (terverifikasi dari disk + manifest)

| Item | Hasil |
|---|---|
| Berkas arsip bulanan | 3.663 bulan-simbol |
| futures 1h | **11/11 pair × 48 bulan = 385.704 baris** |
| funding rate 8h | 48 bulan per pair (11/11) |
| spot 1h | 47 bulan per pair (11/11) |
| Rentang efektif | `2022-10-01` → `2026-09-30` (bulanan) + bulan berjalan dari arsip **harian** |
| Ukuran total | ~84 MB (`data/r4/binance/`) |
| Manifest | `reports/sodex/R4_dataset_manifest.json` (tiap berkas: sha256, jumlah baris, rentang, asal URL) |

## 2. Dua temuan teknis yang WAJIB dicatat (kejujuran data)

1. **Arsip spot bulanan terbit terlambat ~1 bulan** → `spot/*/2026-09` tidak tersedia bulanan.
   Ditangani: **fallback arsip harian** (`data.binance.vision/.../daily/...`) untuk bulan yang
   arsip bulanannya belum terbit. Tanpa ini, LOCKBOX (§3) akan berlubang di bulan terakhir.
2. **Gagal jaringan ≠ 404.** Versi pertama pengunduh menyamakan keduanya sehingga 333 bulan
   tampak "tidak ada" padahal ada (mis. LTCUSDT tampak hanya 32 bulan). Diperbaiki: status
   `ok` / `404` (memang tidak terbit) / `err` (dicoba ulang). Setelah perbaikan, **semua celah
   terisi** dan `missing_404` hanya berisi bulan yang memang belum diterbitkan (bulan berjalan).

**Definisi sha256 di manifest**: checksum dari **konten CSV gabungan** yang tersimpan di
feather (deterministik & dapat diverifikasi), bukan checksum zip — karena berkas hasil
rakitan arsip harian tidak punya satu zip tunggal.

## 3. Universe — TIDAK berubah

11 major tetap: BTC ETH SOL BNB XRP DOGE ADA AVAX LINK DOT LTC.
LTC **tetap ikut** (48 bulan lengkap setelah celah jaringan terisi) — tidak ada pair yang
dikeluarkan karena alasan data. Enam pair listing-baru (SUI, ARB, INJ, NEAR, ASTER, LIT)
tetap dikeluarkan karena alasan **umur listing** (bias survivorship), bukan karena data.

## 4. Konsekuensi untuk evaluasi

- DEV: 2022-10-01 → 2025-09-30 → **lengkap** untuk 11 pair (futures + spot + funding).
- LOCKBOX: 2025-10-01 → 2026-09-30 → **lengkap**; bulan berjalan (2026-10) hanya sebagian
  dan **tidak** dipakai untuk putusan (lockbox berakhir 30-Sep-2026).
- Evaluasi TIDAK dimulai sebelum hipotesis H1–H5 disetujui Mas Anas.

---

*Hermes Anantara v3 · Target 0,8%/48j harga mati · tidak ada batas keamanan yang dilonggarkan.*
