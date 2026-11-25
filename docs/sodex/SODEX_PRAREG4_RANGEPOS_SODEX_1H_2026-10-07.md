# PRAREG-4 — RANGEPOS rank-proporsional di panel SoDEX 1h (100 nama)

**Dibekukan:** 2026-10-07 · **Registry trial:** 42 · **Status: BEKU — commit SEBELUM evaluasi**
**Label keluaran: DESKRIPTIF** (jendela 1h SoDEX sudah terpakai; lihat §6)

---

## 1. Mengapa pra-registrasi ini ada

Rantai bukti SoDEX punya **kontradiksi yang belum terselesaikan**:

| Panel | Konstruksi | Horizon | Hasil | Sumber |
|---|---|---|---|---|
| SoDEX **1d**, 84 nama, 138 periode | rank-proporsional | hold 2 hari | **+7,91 bps** (MOMENTUM), t=0,96 | PRAREG-2 |
| SoDEX **1h**, 63 nama, 291 periode | rank-proporsional | hold 24 jam | **−16,61 bps** (REVERSAL), t=−4,07 | PRAREG-2 |

**Horizon keduanya ≈ 1 hari, tandanya berlawanan.** Salah satu pasti artefak. Yang berubah
antara keduanya: resolusi bar, jumlah nama (63 → sekarang **100**), dan granularitas sampling.

Panel 1h sekarang **100 nama** (dari 63) karena backfill venue yang baru. Karena itu kontradiksi
ini layak diuji ulang dengan mesin yang sama persis seperti PRAREG-2.

### Koreksi yang mendahului pra-reg ini (wajib dibaca)
Klaim saya sebelumnya di `SODEX_COLLECTOR_BREADTH_STATUS_2026-10-07.md` bahwa *"konstruksi
kuintil menaikkan Sharpe 2,5×"* adalah **SALAH** dan sudah ditarik — string itu tidak ada di
satu pun hasil beku. Angka sebenarnya pada panel Binance 1d:

| Konstruksi | Bobot | S_ann | t_NW |
|---|---|---:|---:|
| **rank-proporsional** (PRAREG-2 OOS) | ∝ peringkat, seluruh nama | **1,749** | 2,80 |
| kuintil (PRAREG-3) | equal-weight 1/5 | 1,22 | 3,75 |
| desil (PRAREG-3) | equal-weight 1/10 | 1,15 | 3,51 |

**Rank-proporsional = konstruksi dengan Sharpe terukur terbaik.** Karena itu pra-reg ini
menguji **rank-proporsional**, bukan kuintil. (Kuintil tampak lebih tinggi pada *t* hanya
karena *n* lebih besar, bukan karena efeknya lebih kuat.)

## 2. Hipotesis (falsifiable)

> **H4:** Pada panel SoDEX 1h (100 nama), konstruksi rank-proporsional atas sinyal RANGEPOS
> menghasilkan **spread MOMENTUM** (long yang dekat puncak, short yang dekat dasar) pada
> **sekurang-kurangnya satu** horizon `h` di grid yang dibekukan, dengan `t_NW ≥ 2,0` dan
> lolos BH-FDR — yaitu **tanda yang sama dengan yang tervalidasi di Binance 1d**.

**Prediksi jujur saya (ditulis sebelum melihat hasil):** saya **tidak yakin**. Bukti sebelumnya
di 1h (hold=24) justru REVERSAL dengan t kuat (−4,07). Jika konstruksi rank-proporsional
mengubah hasil, itu bukti konstruksi — bukan horizon — yang menentukan. Jika tidak mengubah,
kontradiksi terselesaikan ke arah "tanda bergantung horizon/sampel" dan jalur 1h ditutup.

**Ini yang membuat ujian ini layak:** bila ada horizon yang lulus di 1h, kita mendapat
**24× lebih banyak periode independen per hari kalender** daripada 1d — itu menyerang masalah
*kekuatan uji* (n) tanpa menunggu 203 hari dan tanpa menyentuh ambang, target, atau modal.

## 3. Spesifikasi BEKU (tidak boleh diubah setelah hasil keluar)

| Komponen | Nilai beku | Asal |
|---|---|---|
| Panel | `data/sodex_klines/1h` via `_sodex_panel("1h")` | 100 nama × 8.525 bar, 2025-10-12 → 2026-10-07 |
| Sinyal | `range_position(px, 20)` = `(close − lo₂₀)/(hi₂₀ − lo₂₀)` | **verbatim PRAREG-2** |
| Bobot | `rank_w` = proporsional-peringkat lintas-seksi, dollar-neutral, Σ\|w\|=1 | **verbatim `xsec_mech_study`** |
| Eksekusi | `run_mech` (harness yang sama dengan PRAREG-2, `market-neutral` = `fwd − mean(fwd)`) | **verbatim** |
| Grid hold | `h ∈ {1, 2, 4, 8, 12, 24, 48}` bar (7 sel) | dibekukan di sini |
| Step | non-overlap, langkah = `hold` | dari `run_mech` |
| Annualisasi | `PPY = 365 × 24` (bar 1 jam) | mengikuti PRAREG-2 |
| Fee | `FEE_ONEWAY = 4 bps`/sisi; stress **×2**; realistis **×1,215** (≈9,71 bps RT) | konstanta venue |
| Min nama/periode | `MIN_NAMES = 20` | konstanta |
| Koreksi banyak-uji | **BH-FDR q = 0,10** atas **7 sel** | dibekukan di sini |
| Seed | 20261007 | dibekukan di sini |

### Ambang LULUS (SEMUA wajib benar; tidak ada yang boleh dilonggarkan)
1. **BH-FDR q=0,10 PASS**,
2. **`t_NW ≥ 2,0`**,
3. **`seg+ ≥ 2` dari 3**,
4. **bruto sinyal > bruto kontrol-acak** (kontrol tidak boleh lulus),
5. **tanda = MOMENTUM (positif)** — tanda yang tervalidasi di Binance 1d.

Ambang ini **sengaja lebih ketat** daripada PRAREG-2 (yang menuntut S_ann ≥ 2,3 pada OOS
40%). Karena jendela ini sudah terpakai, ambang Sharpe tidak dipakai sebagai gerbang;
gerbangnya signifikansi + konsistensi-segmen + kontrol.

## 4. Kontrol negatif (WAJIB, tiga lapis)

| Kontrol | Cara | Wajib |
|---|---|---|
| **C-a** acak-dalam-baris | `run_mech(..., control=True)`: sinyal diacak per baris, konstruksi identik | **tidak lulus** |
| **C-b** sinyal-acak-penuh | matriks sinyal diganti seragam-acak per baris → mengukur artefak konstruksi portofolio (inilah yang dulu memerahkan bendera di PRAREG-3: kontrol acak 7,61 vs sinyal 9,19) | **tidak lulus**, dan sinyal harus **melebihi**-nya |
| **C-c** panel sintetis | random-walk berukuran sama → dijalankan pada skrip yang sama | **tidak lulus** (seluruh grid) |

C-b bersifat wajib karena justru inilah kontrol yang menangkap artefak breadth/portofolio.
Tanpa C-b, hasil positif tidak boleh dipercaya.

## 5. Yang akan mengubah arah kerja

| Hasil | Konsekuensi |
|---|---|
| Ada sel lulus (momentum, BH PASS, t≥2, kontrol bersih) | SoDEX 1h membawa mekanisme terpakai → prioritas **verifikasi forward 1h** (24× periode/hari) |
| Semua gagal; hanya reversal yang kuat | Kontradiksi selesai: 1h = reversal → **jalur 1h ditutup**, fokus ke 1d + forward |
| Hasil bergantung konstruksi secara liar | Sinyal rapuh → **tidak boleh** masuk produksi apa pun |

## 6. Label kejujuran (tidak bisa dilewati)

Jendela 2025-10-12 → 2026-10-07 **sudah terpakai** (PRAREG-2 memakai 63 nama di jendela yang
sama). Maka:

> Semua angka dari pra-reg ini adalah **DESKRIPTIF**. Sah dilaporkan. **TIDAK sah** dipakai
> sebagai verdict lulus/gagal. Verdict yang sah hanya dari data **FORWARD**.

Skripnya akan mencetak penanda ini sendiri supaya tidak bisa terlupakan saat membaca keluaran.

## 7. Amendemen

Amendemen pra-reg **hanya boleh MEMPERKETAT** ambang, dan wajib dicatat di dokumen ini dengan
tanggal + alasan **sebelum** evaluasi ulang. Pelonggaran pasca-hasil = pelanggaran protokol.

— Hermes Anantara v3 — 2026-10-07
