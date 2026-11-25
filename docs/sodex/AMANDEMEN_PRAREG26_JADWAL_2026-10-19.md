# AMANDEMEN-1 PRAREG-26 — JADWAL VERDICT 25-NOV-2026 & AMBANG t 3,80

**Tanggal:** 19-Okt-2026 09:55 WIB (02:55Z) · **Disetujui:** Mas Anas (chat, 19-Okt-2026)
**Protokol induk:** `docs/sodex/PRAREG_26_MESIN_SELEKSI.md` (dibekukan 10-Okt-2026)
**Hash protokol induk (v1):** `e06fcb265a25caa24c880949c7cb112b9945d36abad204bfb2d1c368c9cc46d0`
**Sifat:** amandemen jadwal + ambang statistik. **TIDAK** mengubah target, kriteria A/B, aturan seleksi, universe, atau pembagian waktu.

---

## 1. Kalimat yang diamandemen

Protokol induk §6 (baris 76) berbunyi:

> **Tanggal verdict terencana:** **2-Nov-2026**. **Give-up:** **30-Nov-2026** (bila evaluasi belum memungkinkan).

Diganti menjadi:

> **Tanggal verdict terencana:** **25-Nov-2026**. **Give-up:** **30-Nov-2026** (tidak berubah).
> **Ambang uji M5:** **t satu-sisi ≥ 3,80** (naik dari 3,60; lihat §3).

## 2. Alasan (terukur, bukan preferensi)

Snapshot resmi 19-Okt-2026 02:25Z (`reports/sodex/PRAREG26_MESIN_SELEKSI_STATUS.json`):

| Metrik | Nilai |
|---|---|
| Titik keputusan harian berjalan | 8 |
| Trade forward (`exit_ts ≥ 2026-10-12 00:00Z`) | 13 (snapshot 02:25Z; rekonsiliasi manual 14) |
| **Window 30 jam berisi** | **2 dari minimum 12** |
| Mesin lolos seleksi terakhir | 0 (buku FLAT) |

Laju window terisi yang teramati (dihitung ulang 19-Okt 09:40 WIB dari 10 berkas `paper_test_*_state.json`, 14 trade forward): **0,28 window/hari**.

| Tanggal | Proyeksi window (laju 0,28/hari) | Cukup 12? |
|---|---|---|
| 2-Nov-2026 (jadwal lama) | ≈ 6 | **Tidak** → verdict hanya bisa "DITUNDA/GAGAL-DATA" |
| **25-Nov-2026 (jadwal baru)** | **≈ 12,1** | **Ya, tepat di ambang** |
| 30-Nov-2026 (give-up) | ≈ 13,5 | Ya |

Penyebab tambahan yang terdokumentasi: mesin **realwide buta 11–19 Okt** (semua pair `empty_ohlcv`, 6 posisi beku 179–189 jam; lihat `PROGRES_2026-10-19.md` §3b/§3c). Arm ini adalah salah satu dari 3 mesin net-positif historis; ketiadaannya menekan jumlah window terisi.

**Kesimpulan:** jadwal lama tidak dapat menghasilkan verdict yang sah (data < 12 window), sehingga mengeksekusinya pada 2-Nov hanya akan mencatat "GAGAL" karena kekurangan data — bukan karena strategi gagal. Menunda ke 25-Nov memberi peluang pertama yang nyata untuk verdict yang sah.

## 3. Konsekuensi statistik wajib: ambang t naik

§6 protokol induk: *"setiap amandemen menaikkan ambang t"*. Amandemen ini dibuat **setelah** melihat data (data-informed), sehingga menambah satu titik evaluasi.

Aturan Bonferroni yang dipakai (N = 164 uji di registry, alpha keluarga 0,05):

| Jumlah look | alpha per uji | z kritis |
|---|---|---|
| 2 (dasar, dipakai 3,60) | 0,05 / (164×2) = 1,524e-4 | 3,611 |
| 3 | 0,05 / (164×3) = 1,016e-4 | 3,715 |
| **4 (dipakai; 2-Nov + 25-Nov + 30-Nov + 1 cadangan)** | 0,05 / (164×4) = 7,622e-5 | **3,787 → dibulatkan ke atas 3,80** |

**T_CRIT baru = 3,80** (dari 3,60). Tidak ada pengurangan kekakuan; semua kriteria lain tetap.

## 4. Yang TIDAK berubah (ditegaskan)

1. Target **0,8% dari TOTAL modal wallet per window 30 jam** — harga mati.
2. Definisi **A DAN B**, grid 30 jam jangkar 2026-08-03Z, window kosong dilewati, minimum 10 window (definisi resmi `AMANDEMEN_TARGET_AB_2026-10-10.md`).
3. Aturan seleksi mesin: ≥20 trade dalam 14 hari **dan** net PnL > 0 pada titik keputusan 00:00Z; keputusan berlaku pada `entry_ts`.
4. Universe beku 10 mesin; mesin baru tidak otomatis masuk.
5. **Minimum 12 window berisi** sebelum verdict; **verdict dini dilarang**.
6. **Give-up 30-Nov-2026**; forward start 2026-10-12 00:00Z.
7. Anti look-ahead: seleksi hanya memakai `exit_ts ≤ T`.

## 5. Klarifikasi implementasi (bukan perubahan kriteria)

Ditemukan saat audit 19-Okt: skrip `scripts/research/prereg26_mesin_seleksi.py` mencetak `LULUS`/`GAGAL` begitu jumlah window ≥ 12, **tanpa menunggu tanggal verdict** — melanggar §6 "verdict dini DILARANG". Selain itu, bila data < 12 pada tanggal verdict, skrip menulis `GAGAL`, padahal §6 menyatakan **"DITUNDA, bukan dipaksakan"**.

Perbaikan (sesuai teks §6, bukan mengubahnya):

| Kondisi | Status yang benar |
|---|---|
| `now < 25-Nov` dan window ≥ 12 | **SIAP** — metrik dihitung, keputusan ditahan sampai tanggal verdict |
| `now < 25-Nov` dan window < 12 | **MENUNGGU** |
| `25-Nov ≤ now < 30-Nov` dan window < 12 | **DITUNDA** — data kurang, sampai give-up |
| `now ≥ 30-Nov` dan window < 12 | **TIDAK_TERUJI** (data kurang) — bukan GAGAL |
| `now ≥ 25-Nov` dan window ≥ 12 | **LULUS** atau **GAGAL** menurut 5 kriteria |

Tambahan konsistensi sampel: trade dengan penanda `stale_exit` (exit terlambat karena feed mati,
seperti insiden realwide 11–19 Okt) **dikeluarkan** dari sampel PRAREG-26 — sama dengan perlakuan
di `sodex_maturation_tracker.py`. Harga exit trade semacam itu bukan harga saat exit seharusnya,
sehingga tidak sah untuk verdict. Ini penyaringan kualitas data, bukan perubahan kriteria.

## 6. Risiko yang diakui

1. Proyeksi 12,1 window **tepat di ambang**; bila laju turun (mesin berhenti/feed mati), verdict 25-Nov tetap **DITUNDA** sampai 30-Nov.
2. Menunda verdict memperpanjang periode tanpa keputusan komposisi buku; kerugian paper berlanjut bila mesin net-negatif masih aktif (risiko paper, bukan uang nyata — `LIQ_DRY=1`).
3. Amandemen ini data-informed; itulah alasan ambang t dinaikkan, bukan dipertahankan.

## 7. Jejak integritas

| Item | Nilai |
|---|---|
| Hash protokol induk v1 (10-Okt) | `e06fcb265a25caa24c880949c7cb112b9945d36abad204bfb2d1c368c9cc46d0` |
| Hash protokol induk v2 (setelah §10 ditambahkan) | tercatat di `PRAREG_26_MESIN_SELEKSI.md.sha256` dan `PRAREG_26_HASH_CHAIN.md` |
| Hash dokumen amandemen ini | tercatat di `AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md.sha256` |
| Persetujuan | Mas Anas — "Approve Pra Reg 25 Nov" (19-Okt-2026) |

*Amandemen-1 PRAREG-26 · Hermes Anantara v3 · 19-Okt-2026 · read-only, tanpa order*
