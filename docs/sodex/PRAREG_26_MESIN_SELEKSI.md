# PRAREG-26 — UJI FORWARD SELEKSI MESIN (DROP MESIN NET-NEGATIF)

**Dibekukan:** 10-Okt-2026 (sebelum data 11-Okt ada) · **Sifat:** READ-ONLY, tanpa order, tanpa posisi, tanpa flag live
**Cakupan:** hanya **PENGHAPUSAN mesin** dari buku. **Tidak** mengarang trade. **Memperbanyak SHORT = mesin baru → di luar cakupan** (dilarang di sini).
**Hash dokumen:** tercatat di `docs/sodex/PRAREG_26_MESIN_SELEKSI.md.sha256` (dibuat setelah teks beku).

---

## 1. Latar (terukur, 10-Okt-2026)

Pengukuran seluruh buku (`reports/sodex/AB_TARGET_2026-10-10.md`, skrip `scripts/research/ab_measure.py`):

| Kelompok | n trade | net $ |
|---|---|---|
| 3 mesin net-positif (twoway, realwide, swing) | 1.046 | **+363,57** |
| 7 mesin net-negatif (aster, hyperliquid, pasar_anantara_trade, portfolio, shortbear, donchian, spot_swing_v2) | 1.005 | **−522,11** |
| **Buku penuh** | **2.051** | **−158,54** |

Selisih **$885,68** = tuas terbesar yang terukur sejauh ini (lebih besar dari semua lever biaya/fill/buku yang sudah ditutup). Karena pemilihan mesin dari data yang sama = **seleksi in-sample**, ia **wajib** diuji forward dengan aturan mekanis yang dibekukan **sekarang**.

## 2. Hipotesis

**H1:** Buku yang hanya berisi mesin **yang lolos aturan seleksi mekanis** (bagian 3) menghasilkan metrik target **lebih baik daripada buku penuh** pada periode forward, dan (kriteria penuh di bagian 6) mampu mencapai syarat **A DAN B** pada grid tetap 30 jam.

**H1b (lebih lemah, diprediksi benar):** subset terpilih **mengurangi kerugian** (selisih $ positif) tanpa mampu mencapai A DAN B.

## 3. Aturan seleksi (BEKU — dilarang diubah)

Pada setiap titik keputusan harian **00:00Z** mulai 2026-10-12:

Sebuah mesin **LOLOS** jika **keduanya** benar:
1. **≥ 20 trade** dengan `exit_ts` di **[T − 14 hari, T)**, dan
2. **net PnL > 0** pada jendela 14 hari itu.

**Buku yang diuji** = gabungan trade mesin yang LOLOS, dihitung pada window 30 jam grid tetap.
**Penerapan (presisi):** trade dihitung masuk buku bila mesinnya LOLOS pada titik keputusan terakhir yang **≤ `entry_ts`** trade itu (keputusan diambil saat entry, bukan saat exit).

**Bila nol mesin lolos → buku FLAT** (tidak ada trade; window dihitung 0,0% — bukan diabaikan).
Mesin yang **tidak lolos tidak ditradingkan** (asetnya diam).

**Universe beku (10 mesin, tidak boleh ditambah tanpa amandemen):**
`aster, donchian, hyperliquid, pasar_anantara_trade, portfolio, realwide, shortbear, spot_swing_v2, swing, twoway`.
Mesin baru yang muncul kemudian **tidak otomatis masuk**.

**Anti look-ahead:** seleksi hanya memakai trade dengan `exit_ts ≤ T` (realisasi). Tidak ada nilai/pnl setelah T. Tidak ada tuning parameter.

## 4. Data & pembagian waktu

- Sumber: `data/paper_test_*_state.json` (hanya trade uang-paper; bukan uang nyata), `exit_ts` sebagai penanda realisasi.
- **Latih/telaah (deskriptif, in-sample):** s/d 10-Okt-2026 — hanya untuk kelayakan & prediksi (bagian 7).
- **Forward (verdict):** trade dengan `exit_ts ≥ 2026-10-12 00:00Z`.
- Window gerbang: **30 jam**, grid tetap jangkar 2026-08-03Z, window kosong dilewati (definisi resmi, lihat `docs/sodex/AMANDEMEN_TARGET_AB_2026-10-10.md`).

## 5. Metrik

| Kode | Metrik | Definisi |
|---|---|---|
| M1 | mean window subset | akumulasi pnl subset per window 30 jam ÷ wallet |
| M2 | mean window buku penuh | idem, seluruh 10 mesin |
| M3 | median window subset | — |
| M4 | hit rate subset | porsi window subset ≥ 0,8% |
| M5 | selisih berpasangan | M1(window) − M2(window) pada window yang sama |
| M6 | net $ subset vs penuh | sekunder, informatif |

Wallet denominator: TOTAL wallet divisi dari snapshot on-chain (metrik total-modal, sama seperti tracker).

## 6. Kriteria verdict (BEKU — semua wajib benar untuk "LULUS")

1. **M1 ≥ M2** (subset tidak lebih buruk dari buku penuh), **dan**
2. **M1 ≥ 0,8%**, **dan**
3. **M3 > 0**, **dan**
4. **M4 ≥ 50%**, **dan**
5. **M5 > 0** dengan **t satu-sisi ≥ 3,6** pada window berisi (ambang registry N≈164; Bonferroni).
   > ⚠ **DICABUT oleh Amandemen-1 (§10): ambang berlaku = t ≥ 3,80.**

**Minimum data sebelum verdict:** **≥ 12 window penuh berisi** (≈ 15 hari). Jika belum tercapai → **verdict DITUNDA**, bukan dipaksakan.
**Tanggal verdict terencana:** **2-Nov-2026**. **Give-up:** **30-Nov-2026** (bila evaluasi belum memungkinkan).
> ⚠ **DICABUT oleh Amandemen-1 (§10, 19-Okt-2026): verdict = 25-Nov-2026, t ≥ 3,80. Give-up tetap 30-Nov.**
**Verdict dini DILARANG.** Monitor harian bukan dasar keputusan (anti *optional-stopping*).
**Penarikan (withdrawal)/perubahan aturan:** hanya lewat **amandemen tertulis** dengan persetujuan user; setiap amandemen menaikkan ambang t.

## 7. Prediksi jujur (ditulis SEBELUM data forward ada)

Uji kelayakan **deskriptif in-sample** (bukan verdict) pada 21 jendela 14-hari bergulir 20-Sep → 10-Okt:

- Subset terpilih lebih baik dari buku penuh di **20/21 jendela**; rata-rata selisih **+$91,28**, median **+$29,03**.
- **6/21 jendela** tidak ada mesin yang lolos → buku flat; semuanya terjadi di Okt saat seluruh mesin rugi. Mekanisme utama aturan = **"berhenti trading ketika semua mesin sedang rugi"** (circuit breaker), bukan menemukan alpha baru.
- Karena itu **prediksi pra-registrasi**: **H1b benar (kerugian berkurang)**, **H1 penuh diprediksi GAGAL** (mean ≥ 0,8% / median > 0 / hit ≥ 50% tidak tercapai). Bila H1 ternyata lolos penuh, itu hasil di luar prediksi → wajib dicek ulang sebelum dipakai.
- Peringatan metodologis: window bergulir **tumpang tindih** (autokorelasi), seluruh uji kelayakan **in-sample**, n jendela kecil → angka di atas **bukan** estimasi OOS.

## 8. Risiko & biaya yang diakui

1. Risiko **melewatkan rebound** (mesin dimatikan tepat sebelum pulih) — biaya oportunitas tak terukur di muka.
2. Risiko **seleksi mengejar performa lampau** (performance chasing) yang bisa berarti mematikan mesin yang sedang di titik terburuknya.
3. Overhead operasional: perubahan komposisi mesin harian.
4. **Tidak** menyentuh uang nyata (semua track masih paper); verdict hanya mengubah **komposisi buku yang diuji**, bukan posisi.

## 9. Reproduksi

```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/ab_measure.py                    # A & B seluruh buku
/usr/bin/python3 scripts/sodex_maturation_tracker.py               # gerbang resmi (A DAN B, grid tetap)
```

*PRAREG-26 · Hermes Anantara v3 · dibekukan 10-Okt-2026 · read-only*

---

## 10. AMANDEMEN-1 (19-Okt-2026) — jadwal verdict 25-Nov-2026, ambang t ≥ 3,80

Bagian §6 baris *"Tanggal verdict terencana: 2-Nov-2026"* **diganti** menjadi **25-Nov-2026**;
ambang uji M5 **t ≥ 3,60 → t ≥ 3,80** (Bonferroni 4 look; aritmetika di dokumen amandemen).
**Give-up tetap 30-Nov-2026.** Target 0,8%, kriteria A/B, aturan seleksi, universe 10 mesin,
minimum 12 window, dan anti look-ahead **tidak berubah**.

Dasar keputusan (19-Okt-2026 02:25Z): 2/12 window berisi, 13 trade forward, laju 0,28 window/hari
→ proyeksi 2-Nov ≈ 6 window (tidak sah untuk verdict), 25-Nov ≈ 12,1 window.
Dokumen lengkap: `AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md`.

