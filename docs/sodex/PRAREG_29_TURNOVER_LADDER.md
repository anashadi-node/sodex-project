# PRAREG-29 — MOMENTUM CROSS-SECTIONAL DENGAN TURNOVER DITURUNKAN (LADDER R = 3/7/14)

**Dibekukan:** 22-Okt-2026, SEBELUM skrip evaluasi PRAREG-29 dijalankan.
**Pijakan:** PRAREG-28 (GAGAL, hash `434bb67…`) — turnover 137×/tahun pada rebalance harian membunuh edge di biaya 25bps; dan **temuan korektif penting**: tanpa 3 kontributor teratas (LUNA/USDT, XRP, ADA), return 25bps jatuh ke **−74,2% (Sharpe −0,43)**, jadi klaim "jejak edge riil" pada PRAREG-28 **belum terbukti lebar** — bisa jadi artefak 1 peristiwa struktural (keruntuhan LUNA).
**Sifat:** READ-ONLY, backtest historis. Tanpa order, tanpa posisi, tanpa flag live.

---

## 1. Dua pertanyaan yang diuji (dipisah tegas)

**Q1 (struktural):** Apakah edge PRAREG-28 bertahan bila turnover diturunkan ke tingkat yang wajar dibiayai 25bps?
**Q2 (kejujuran sinyal):** Apakah edge itu **lebar** (tetap positif tanpa 3 nama terbaik), atau hanya artefak 1–3 nama?

Q2 **bukan** catatan sampingan — ia gerbang wajib (gerbang h). Alasannya: mekanisme yang hanya hidup karena satu keruntuhan exchange tidak dapat diandalkan untuk 0,8% per window secara berulang, dan menurut standar V2 §9 kandidat seperti itu harus ditolak.

## 2. Yang diubah dari PRAREG-28 (hanya satu parameter)

Hanya **R = periode rebalance dalam hari trading**. Semua yang lain **identik**: universe top-20 likuid (fungsi `build_universe` PRAREG-25, tidak dibangun ulang), K=14, leg 25%/25%, gross 1,00 (0,50 long / 0,50 short), net 0,00, equal-weight, tanpa vol-targeting, biaya `|Δbobot| × cost`, jendela terverifikasi `≤ 2025-10-09`.

**K=7 TIDAK diuji ulang** — PRAREG-28 sudah membuktikan K=7 lebih buruk pada Sharpe (−0,25 vs +0,05) DAN turnover lebih tinggi (190× vs 137×). Menguji ulang hanya menambah beban multiple-testing tanpa alasan.

### Ladder (ketiganya dilaporkan, tidak ada "pilih yang terbaik")

| Varian | R | Turnover perkiraan (dari 137× dibagi R) | Beban biaya @25bps/thn | Peran |
|---|---|---|---|---|
| **V1 (PRIMER)** | **7 hari** | ≈19,6× | ≈4,9% | pilihan apriori: memenuhi target desain turnover ≤25×/thn, daya statistik masih cukup (≈425 rebalance) |
| V2 | 3 hari | ≈45,7× | ≈11,4% | kontrol tengah — kalau V2 gagal & V1 lolos, artinya biaya memang penentu |
| V3 | 14 hari | ≈9,8× | ≈2,4% | batas atas perlambatan — menguji apakah makin lambat makin baik, atau sinyal basi |

Perkiraan turnover di atas dihitung **hanya dari aritmetika biaya** (137× ÷ R), **tidak** dari return PRAREG-29. R=7 dipilih sebagai primer karena memenuhi target desain ≤25×/tahun dan tetap memberi ≥400 titik rebalance; bukan karena hasil terbaik.

## 3. Mekanisme (BEKU)

1. Pada hari rebalance (setiap hari ke-R dari awal seri, dihitung pada kalender hari data), hitung `ret_14(s,t) = close[t]/close[t−14] − 1` untuk semua simbol eligible di universe bulan itu.
2. LONG = 5 nama teratas (25% dari 20, pembulatan ke bawah, minimum 2); SHORT = 5 terbawah; equal-weight; total +0,50 / −0,50.
3. **Di antara hari rebalance: bobot dibiarkan mengambang** (tidak direnormalisasi, tidak disentuh). Ini yang menurunkan turnover secara riil, bukan sekadar kosmetik.
4. Bila eligible < 8 pada hari rebalance → target kosong (posisi ditutup), dilaporkan sebagai `n_empty_rebalances`.
5. Universe berganti bulan → rebalance berikutnya memakai universe bulan baru (otomatis, tanpa aturan tambahan).

## 4. Biaya & diagnostik

- **Primer:** 25 bps/sisi. **Sekunder:** 10 bps/sisi (pembanding dengan PRAREG-28).
- **Diagnostik (BUKAN gerbang):** 0 bps, untuk memisahkan *sinyal kotor* dari *beban biaya* — ini yang menjawab Q1 vs Q2 secara bersih.

## 5. Gerbang (BEKU — dinyatakan sebelum data disentuh)

| # | Kriteria | Catatan |
|---|---|---|
| a | Sharpe @25bps > 0 | |
| b | maxDD absolut ≤ 20% | |
| c | Positif di ≥2 dari 3 sub-periode @25bps | 2019-21, 2022-23, 2024-26 |
| d | ≥60% blok 20-hari positif **dan** median blok > 0 @25bps | |
| e | p-value satu-sisi (bootstrap blok 20 hari, **B=20.000**) < α | α = 0,05 / (n_registry + 3 varian); n registry = 132 → **α = 0,05/135 = 3,70e-4**. B=20.000 dipakai agar resolusi p (5e-5) lebih halus dari α — PRAREG-28 memakai B=2.000 yang resolusinya (5e-4) **lebih kasar dari α**, cacat yang diperbaiki di sini |
| f | %/48 jam @25bps ≥ **0,10%** (lantai tangga) | bukan 0,8% — tangga resmi 22-Okt |
| g | DSR > 0,95 (n_trials = registry aktual) | |
| **h** | **ROBUSTNESS WAJIB:** tanpa 3 kontributor P&L terbesar, %/48 jam @25bps **dan** @0bps keduanya ≥ 0,10% | gerbang inti Q2 — inilah yang membedakan edge lebar dari artefak LUNA |
| i | Turnover ≤ 30×/tahun (V1) | pemeriksaan bahwa desain bekerja sesuai maksud; V2/V3 dilaporkan apa adanya |

**Definisi verdict (dibekukan):**
- **LULUS PENUH** = a–i semua benar.
- **KANDIDAT HIDUP** = a, e, f, g, h benar tetapi b/c/d gagal → boleh dikembangkan, **tidak** boleh modal nyata.
- **GAGAL** = selain itu.

**Aturan penutupan keluarga (dibekukan):** bila gerbang **h** gagal pada **ketiga** varian, maka **keluarga momentum cross-sectional dinyatakan TUTUP** — tidak ada varian R lain, tidak ada ubah K, tidak ada ubah band. Alasan: Q2 terjawab negatif, jadi seluruh keluarga tidak punya edge lebar yang bisa diselamatkan parameter apa pun.

## 6. Yang TIDAK dilakukan

Tidak menguji hysteresis band, tidak vol-targeting, tidak mengubah gross exposure, tidak menyentuh data SoDEX forward, tidak mengubah arm A/B mana pun.

## 7. Reproduksi

```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/prereg29_turnover_ladder.py
# keluaran: reports/sodex/PRAREG29_HASIL.json
```

## 8. Disiplin

Di-hash sebelum skrip ditulis. Tidak ada ambang dilonggarkan setelah melihat hasil. Ketiga varian masuk registry SEBELUM laporan penutupan ditulis.

*PRAREG-29 · Hermes Anantara v3 · dibekukan 22-Okt-2026 · read-only*
