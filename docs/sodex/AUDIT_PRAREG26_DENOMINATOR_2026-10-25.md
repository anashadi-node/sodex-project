# AUDIT PRAREG-26 — DENOMINATOR & VERIFIKASI GANDA

**Tanggal:** 2026-10-25 07:5x UTC (14:5x WIB)
**Status:** DESKRIPTIF/AUDIT — bukan amandemen, bukan pra-registrasi baru
**Objek audit:** `scripts/research/prereg26_mesin_seleksi.py`, `scripts/sodex_maturation_tracker.py`,
`reports/sodex/PRAREG26_MESIN_SELEKSI_STATUS.json`, protokol `PRAREG_26_MESIN_SELEKSI.md`
+ `AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md`

---

## 1. Ringkasan satu paragraf

Audit ganda menemukan **satu bug nyata yang sudah diperbaiki** (denominator wallet *fail-open* saat
mark-to-market spot gagal → wallet understated 21–31% → semua % ROI ter-inflasi) dan
**tiga perbedaan replikasi yang semuanya berada di kode audit saya sendiri, bukan di skrip
produksi**. Setelah perbaikan, replikasi independen mereproduksi angka produksi **persis**
(2.195 trade, 166 trade forward, 14 titik keputusan, 7 window, 0 subset, 0,525 window/hari).
Kesimpulan: **logika PRAREG-26 valid**, tetapi **kriteria subset (M3/M4) hampir pasti gagal
pada 25-Nov** karena 9/9 mesin yang aktif 14 hari terakhir semuanya net negatif (−$345,10).

---

## 2. Temuan A1 — Denominator *fail-open* (BUG NYATA, DIPERBAIKI)

**Kelas bug:** sama dengan kelas `rc=0, orderID=0` (Rule 7 riset-penelitian: harness wajib fail-closed).

**Mekanisme:**
1. `sodex_realtime_sync.py` menulis `spot_equity_usd` hanya bila mark harga spot berhasil.
2. Snapshot 2026-10-25 07:48Z: `spot_mark_error = "HTTP 429 Too Many Requests"` → kunci
   `spot_equity_usd` **tidak ada**.
3. `sodex_maturation_tracker._read_live_wallet()` membaca `spot_equity_usd or 0` → spot = 0.
4. Guard `spot + perps >= 20` **lolos** karena perps = $184,97 → wallet dilaporkan **$184,97**
   padahal wallet sebenarnya **$243,02** (spot vUSDC $49,28 + posisi spot kecil + perps).
5. Semua metrik % (window mean/median/hit, target 0,8%) dihitung di denominator yang
   **terlalu kecil** → **ter-inflasi 31,4%**.

**Dampak terukur:**

| Denominator | Target 0,8% | PnL $1,48 terbaca | Status gate |
|---|---|---|---|
| $184,97 (bug) | $1,48 | **0,80%** | LOLOS (palsu) |
| $243,02 (benar) | $1,94 | **0,61%** | GAGAL |

**Fix (surgical, sudah diterapkan):**
- Fallback `spot_vusdc.total` bila `spot_equity_usd` absen.
- Label eksplisit `+SPOT_UNMARKED(lower-bound)` pada `wallet_source` bila `spot_mark_error` ada,
  sehingga denominasi *lower-bound* tidak pernah lagi dipakai diam-diam.
- Verifikasi sesudah fix: tracker 07:50Z → `$243,02 [onchain_snapshot@10-25 07:50Z]`.

**Catatan penting:** angka $262,77 pada status 01:25Z **bukan** bug — snapshot saat itu punya
mark spot lengkap; wallet memang bergerak $262,77 → $243,02 dalam ~6 jam (spot vUSDC berubah).
Bug hanya terjadi pada jendela ketika mark gagal.

---

## 3. Temuan A2 — Kriteria #5 (t≥3,80 pada M5) invarian terhadap denominator

M5 = (M1_window − M2_window)/wallet per window. Pembagi sama untuk semua window →
**statistik t dari uji berpasangan tidak berubah** oleh skala denominator
(t = mean(d)/sd(d)·√n). Artinya:

- Kriteria **#5 tidak terpengaruh** bug A1.
- Kriteria **#2 (M1 ≥ 0,8%), #3 (median M3 > 0), #4 (hit ≥ 50%)** terpengaruh karena absolut.

Kesimpulan metodologis: laporan yang hanya menyajikan t tanpa level % absolut bisa lolos
meski denominator salah — karena itu audit level-per-level (Rule 8) wajib.

---

## 4. Temuan A3 — Verifikasi ganda: 3 perbedaan replikasi, semuanya di kode audit

Replikasi independen (`scripts/research/audit_prereg26_independen.py`, ditulis dari nol, tanpa
mengimpor fungsi skrip produksi) pertama kali menghasilkan angka berbeda. Ketiganya **cacat
replikasi**, bukan cacat skrip:

| # | Gejala | Akar masalah di replikasi | Perbaikan |
|---|---|---|---|
| 1 | 57 vs 166 trade forward | hanya membaca kunci `closed`; file memakai `closed`/`closed_trades`/`trades` | fallback 3 kunci |
| 2 | 306 vs 166 | field waktu beda skema: `exit_ts` / `exit_time` / `exit_iso` | fallback 3 skema |
| 3 | 306 vs 166 (sisa) | trade kontrol `track=RANDOM` ikut terhitung (filter salah field: `label/reason` vs `track/arm/regime`) | filter RANDOM benar |

**Hasil akhir — cocok persis:**

| Metrik | Script produksi | Replikasi audit | Status |
|---|---|---|---|
| Trade universe dibaca | 2.195 | 2.195 | ✅ |
| Titik keputusan (00:00Z) | 14 | 14 | ✅ |
| Trade forward penuh | 166 | 166 | ✅ |
| Trade forward subset | 0 | 0 | ✅ |
| Window 30j berisi | 7 | 7 | ✅ |
| Laju window/hari | 0,525 | 0,525 | ✅ |
| Mesin terpilih terakhir | `[]` | `[]` | ✅ |

**Integritas dokumen:** sha256 `PRAREG_26_MESIN_SELEKSI.md` dan
`AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md` **cocok** dengan berkas `.sha256` masing-masing →
tidak ada perubahan protokol diam-diam.

---

## 5. Status forward per 2026-10-25 07:52Z

```
wallet               : $243,02 (snapshot on-chain 07:50Z, mark lengkap)
titik keputusan      : 14 (12-Okt → 25-Okt, 00:00Z)
trade forward penuh  : 166
trade forward subset : 0          <- belum pernah ada mesin lolos seleksi
window 30j berisi    : 7 / 12 minimum
laju                 : 0,525/hari  → proyeksi 23,1 window pada 25-Nov (ON_TRACK data)
verdict              : MENUNGGU (terencana 25-Nov-2026); cadangan 30-Nov
```

## 6. Risiko forward yang harus dinyatakan sekarang

Statistik 14 hari per mesin (dari replikasi independen):

| Mesin | n | net USD |
|---|---:|---:|
| swing | 103 | −94,29 |
| twoway | 60 | −102,91 |
| realwide | 34 | −65,73 |
| spot_swing_v2 | 38 | −19,80 |
| donchian | 26 | −69,13 |
| hyperliquid | 22 | −89,77 |
| aster | 21 | −83,56 |
| portfolio | 8 | −7,74 |
| shortbear | 5 | −5,10 |
| **Total** | **170** | **−345,10** |

**9 dari 9 mesin aktif net negatif.** Aturan seleksi (≥20 trade & net>0 dalam 14 hari) karena itu
menghasilkan himpunan kosong di **14 dari 14 titik keputusan**. Konsekuensi:

- M3 (median subset) = 0 → kriteria #3 gagal.
- M4 (hit-rate subset) = 0% → kriteria #4 gagal.
- Verdict 25-Nov **akan** "TIDAK LOLOS" kecuali minimal satu mesin berbalik positif dengan ≥20
  trade dalam 14 hari sebelum verdict.

Ini **bukan** alasan mengubah aturan sekarang (itu akan menjadi data snooping). Ini alasan
mencatat risiko di muka, sesuai disiplin pra-registrasi.

---

## 7. Batas audit ini

1. Audit mereproduksi **aturan**, bukan menilai kualitas ekonomi mesin. Mesin yang net negatif
   tetap net negatif.
2. Denominator bergerak mengikuti wallet live; angka % historis berubah bila wallet berubah
   (properti definisi "total modal", bukan bug). Yang diperbaiki hanyalah *fail-open* saat mark gagal.
3. Tidak ada trade baru yang dihasilkan audit; semua angka berasal dari state paper yang ada.
4. Window dihitung dari **exit_ts** (konvensi tracker & protokol); konvensi entry tidak diuji
   ulang di sini.

---

## 8. Rekomendasi falsifiable

| Rekomendasi | Cara memverifikasi |
|---|---|
| Pertahankan fix fail-closed denominator | Injeksi snapshot tanpa `spot_equity_usd` + `spot_mark_error`; wallet wajib ≈ perps+spot_vusdc dan label memuat `SPOT_UNMARKED` |
| Jalankan audit independen setiap minggu sampai verdict | Angka harus cocok persis dengan script produksi; selisih >0 = investigasi |
| Jangan ubah aturan seleksi sebelum verdict | Jika diubah: tulis amandemen + naikkan ambang t sesuai protokol §6 |
| Catat verdict "TIDAK LOLOS (subset kosong)" sebagai hasil sah | Bukan kegagalan harness; kegagalan seleksi ekonomi mesin |
