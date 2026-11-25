# AMANDEMEN-1 PRAREG-30 — KEBijAKAN CELAH DATA & JENDELA REPLIKASI

**Berlaku: 22-Okt-2026, SEBELUM analisis final dijalankan.**
Tidak mengubah satu pun parameter sinyal, biaya, atau gerbang. Hanya mencatat
realitas data yang diukur dan menetapkan cara memperlakukannya.

## 1. Temuan terukur (bukan dugaan)

Kolom `sum_toptrader_long_short_ratio` **kosong** pada sebagian besar 2022,
sementara `sum_open_interest_value` terisi normal. Dihitung langsung dari file:

| Tahun | BTCUSDT | SOLUSDT | ETHUSDT |
|---|---|---|---|
| 2021 | 144.392/144.804 (**100%**) | 8.521/8.921 (96%) | 8.521/8.921 (96%) |
| 2022 | 13.387/105.120 (**13%**) | 13.387/105.120 (**13%**) | 13.387/105.120 (**13%**) |
| 2023 | 105.104/105.117 (100%) | 105.087/105.100 (100%) | 105.104/105.117 (100%) |
| 2024 | 105.264/105.281 (100%) | 105.264/105.281 (100%) | 105.264/105.281 (100%) |
| 2025 | 105.099/105.117 (100%) | 105.099/105.117 (100%) | 105.099/105.117 (100%) |
| 2026 | 84.384/84.384 (100%) | 84.384/84.384 (100%) | 84.384/84.384 (100%) |

Angka 2022 **identik di tiga simbol berbeda** → celah tingkat venue (dataset Binance
Vision), bukan kegagalan unduhan atau parser. URL 2022 mengembalikan HTTP 200;
yang kosong adalah isi kolomnya.

**Konsekuensi:** jendela primer (2024-01-01 → 2026-10-08) **100% utuh** — tidak
terdampak. Hanya jendela replikasi yang terpotong.

## 2. Amandemen

| Butir | Sebelum | Sesudah |
|---|---|---|
| Replikasi (§6) | 2021-01-01 → 2023-12-31 | **2021 penuh + 2023 penuh**; 2022 dikecualikan **mekanis** |
| Aturan sinyal §3 | — | tidak berubah |
| Biaya §5 | — | tidak berubah |
| Gerbang a–g §8 | — | tidak berubah |

**Arah perubahan: memperketat, bukan melonggarkan.** Data berkurang ~1 tahun,
tidak ada ambang yang diturunkan, tidak ada simbol/jam yang dipilih tangan.

## 3. Aturan integritas celah (baru, berlaku untuk SEMUA periode)

Setelah lubang data **> 24 jam**, **720 bar berikutnya tidak boleh menghasilkan sinyal**
(`z` dan `pct` di-set NaN). Alasan: `oi_ret_4h` dan persentil 30 hari menjadi tidak
bermakna bila lag melompati berbulan-bulan. Aturan ini hanya **mengurangi** sinyal.

Konsekuensi terukur: sinyal di replikasi baru boleh muncul mulai **Februari 2021**
dan **Februari 2023** (720 jam setelah awal data / setelah celah).

## 4. Pengungkapan wajib (sebelum hash amandemen ini)

Sebuah **smoke test** dijalankan lebih dulu untuk menguji kode pipeline, dengan
**8 dari 20 simbol** (BTC, ETH, SOL, DOGE, XRP, BCH, HYPE, ONDO) pada 2024-01-01 →
2026-10-08. Tidak ada parameter yang diubah setelahnya.

Hasil smoke (BUKAN hasil PRAREG-30, universe belum lengkap):
`P: E=-26,4 bps WR=46,7% t=-3,18 | C: E=-18,8 bps WR=48,6% | ΔWR=-1,83 pp p=0,617`
— yaitu **negatif dan lebih buruk dari kontrol**.

Diungkapkan agar tidak ada kesan amandemen ini disesuaikan untuk memperbaiki hasil.
Amandemen ini **tidak** menyentuh aturan sinyal; ia hanya menetapkan penanganan
celah data 2022 dan memperjelas jendela replikasi.

## 5. Status

- Dokumen induk tetap beku: `ddac7c1157c5c590532170f14ebf126c8da4eee969428e6bb50de042a1b87281`
  (tidak diubah; guard test tetap hijau).
- Amandemen ini berlaku sebagai adendum. Hash tercatat di `PRAREG_30_HASH_CHAIN.md`.
- Hasil final tetap dinilai dengan gerbang a–g apa adanya.

---

*Amandemen-1 · 22-Okt-2026 · Hermes Anantara v3*
