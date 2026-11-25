# R2C — REKONSILIASI MFE: selesai. Dua-duanya benar; tuas exit tetap mati.

**Tanggal:** 10-Okt-2026 · **Sifat:** read-only, tanpa order
**Runner:** `scripts/research/r2c_rekonsiliasi_mfe.py` · Data: `reports/sodex/R2C_REKONSILIASI_MFE_2026-10-10.json`

## Pertanyaan

H1 (riset 14-Sep) menyimpan **median MFE +1,087R, 52,2% trade sentuh +1R** (n=732). R2B (10-Okt) mengukur **0,871R, 45,3%** pada record forward. Kontradiksi atau bukan — dan kalau bukan, apa artinya bagi tuas capture-exit?

## Metode

Dekomposisi 3 faktor × 12 sel, dengan **rumus & sumber harga yang persis sama** dengan `h1_h3_exit_regime.py` (D = (max high − entry)/entry atau (entry − min low)/entry, dibagi R; window `ts ≥ entry & ≤ exit`; harga Binance futures 1h feather). Faktor: **dataset** (3 track dgn swing, snapshot ≤14-Sep → 3 track semua → 2 track), **sumber harga** (Binance vs SoDEX klines), **konvensi window** (inklusif vs interior).

## Rantai angka (semua sel, sumber & konvensi bervariasi)

| Sel | n | med MFE | ≥+1R | ≥+0,5R |
|---|---|---|---|---|
| **D1** 3 track, exit≤14-Sep, **Binance**, inklusif ← *setting H1* | 463 | **1,019R** | **50,5%** | 70,6% |
| D1, SoDEX | 514 | 0,988R | 49,6% | 69,5% |
| D2 3 track semua, Binance | 870 | 0,975R | 49,1% | 67,1% |
| D2, SoDEX | 1.014 | 0,913R | 47,6% | 65,5% |
| D3 2 track semua, Binance | 535 | 0,890R | 45,8% | 65,0% |
| **D3** 2 track, **SoDEX** ← *setting R2B* | 654 | **0,838R** | **44,2%** | 62,8% |

## VERDICT 1 — Bukan kontradiksi: kedua pengukuran benar pada datanya

- Angka H1 terverifikasi asli dari `H1_H3_RESULT.json` (1,0873 / 0,5219 / n=732) — bukan ingatan.
- Metode H1 berhasil direkonstruksi baris-per-baris; pada data yang tersisa ia mereproduksi **1,019R / 50,5%** — arah dan kelas magnitudo sama dengan tersimpan (1,087R / 52,2%).
- Selisih 1,087→1,019 dan 732→463 = **kehilangan data 26 hari**, terukur dan terjelaskan: state live di-prune (557 trade lama tersisa dari ~960, tanpa backup), 22 simbol lama tak punya feather Binance (SILVER 9, PUMP 8, XAUT 5, dst.), plus record field tak lengkap.
- Tiap faktor mendorong turun bertahap dari 1,087 → 0,838: dataset (−0,044R), sumber harga Binance→SoDEX (−0,032…−0,062R), konvensi window (**0,000 — koinsiden di data nyata**: dari 400 trade, tak satu pun entry pas HH:00:00), drift waktu (D1→D2/D3).
- Cek silang D3-SoDEX (0,838R/44,2%) vs angka R2B (0,871R/45,3%): beda kecil dari definisi R — **dalam toleransi**.

**Klaim H1 benar pada 14-Sep (3 track, Binance); pengukuran R2B benar pada record sekarang (2 track, SoDEX). Tidak ada bug di salah satu pihak.**

## VERDICT 2 — Yang lebih penting: tuas capture +1R TIDAK PERNAH menguntungkan, bahkan di dataset H1 sendiri

Exit penuh di +1R vs exit aktual, gross-vs-gross, konvensi & harga milik H1, TANPA biaya leg tambahan:

| Dataset | n | sentuh +1R | median Δ | **mean Δ per trade** |
|---|---|---|---|---|
| D1 (setting H1) | 463 | 50,5% | +0,0000% | **−0,2293%** |
| D2 (3 track, semua) | 870 | 49,1% | +0,0000% | **−0,1368%** |
| D3 (= setting R2B) | 535 | 45,8% | +0,0000% | **−0,1378%** |

**Rata-rata negatif di ketiganya** — termasuk di dataset September yang melahirkan klaim H1. Median MFE ~1R berarti separuh trade tak pernah sampai; yang sampai justru menutup ekor yang membayar. Gap MFE-vs-realized (temuan H1) itu **nyata sebagai diagnosis**, tapi bukan uang yang bisa diambil dengan exit +1R. H1 mendirikan bottleneck, bukan profitabilitas tuas; D11 dan R2B yang menguji tuasnya — dan tuasnya mati di **semua** dataset, **semua** konvensi, **semua** sumber harga. Biaya leg tambahan hanya membuat lebih negatif → kesimpulan konservatif.

## Lampiran double-check (8 butir, semua dieksekusi)

1. Rumus MFE runner = rumus H1, diverifikasi baris-per-baris dari `h1_h3_exit_regime.py`.
2. Sumber harga sel D1 = Binance futures 1h feather — sama dengan H1.
3. Hand-check manual 2 trade (hitung tangan dari candle) = hasil fungsi (0,2457R = 0,2457R; 0,0049%/0,0199 ✓).
4. Inklusif vs interior: 0/400 trade berbeda — **diuji eksplisit**, bukan diasumsikan.
5. Angka tersimpan H1 dibaca langsung dari JSON hasil, bukan dari dokumen turunan.
6. Mean capture D2/D3 dihitung ulang independen dua kali — cocok (−0,1368% / −0,1378%).
7. Cakupan D1 dihitung eksplisit per track (realwide 106/132, twoway 184/219, swing 173/206) + daftar simbol bolong; 960→557 pruning tak dapat dipulihkan (state tidak di-git).
8. `pyarrow` dipasang `--user --break-system-packages` (PEP 668) — tidak menyentuh paket sistem.

**Batas:** snapshot 14-Sep tak dapat direproduksi penuh (state hidup, di-prune) · klines 1h, bukan tick · `cocok:false` di JSON validasi = selisih kehilangan-data (1,019 vs 1,087), bukan kegagalan metode.

## Implikasi

- Cabang exit D11 **tertutup final**. Tidak ada konfigurasi data yang menyelamatkannya.
- H1 tetap berharga sebagai **diagnosis**: ekor membayar → arah yang benar adalah *biarkan ekor jalan + potong biaya*, bukan *potong ekor*.
- Sisa arah kerja: **biaya/venue (fill maker)**, atau level <+0,5R hanya dengan **pra-registrasi baru + data forward** (R2B/R2C sudah 4 look pada data ini).

*Laporan rekonsiliasi · Hermes Anantara v3 · 10-Okt-2026*
