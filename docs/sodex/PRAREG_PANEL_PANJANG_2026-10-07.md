# PRAREG — Studi Panel Panjang (Binance proxy → replikasi SoDEX)

**Status: DIBEKUKAN SEBELUM DIJALANKAN.** Ditulis 07-Okt-2026, sebelum satu pun
angka panel panjang dihitung. Setelah hasil keluar, berkas ini **tidak diubah**.
Registry trial ekosistem: 39 (setelah 38 = D14).

---

## 1. Mengapa studi ini ada — bottleneck yang terbukti

Sensus D14 (21 mesin) verdict `TIDAK-ADA-MESIN-LULUS`. Analisis lereng:

| mesin | Sharpe_ann (titik) | n_window | p_terburuk |
|---|---|---|---|
| mv_funding | **7,76** | 16 | 0,036 |
| spot_swing_cex | **3,50** | 15 | 0,402 |
| twoway | **2,42** | 31 | 0,345 |
| realwide | 1,98 | 32 | 0,448 |

**Tiga mesin punya Sharpe titik di atas syarat 2,3 — tak satu pun dapat
dibedakan dari nol.** n_window maksimum di SELURUH keluarga = **45**, dari
**180 window** yang tersedia di histori 360 hari SoDEX. Mesin memakai 25%
power yang ada.

Aritmetika power (Sharpe 2,3 → 0,1703 per 48 jam):

| skenario | t_kritis | n_window | hari |
|---|---|---|---|
| 1 mesin, tanpa koreksi | 1,96 | 133 | 265 |
| keluarga 5, BH q=0,10 | 2,33 | 187 | 375 |
| keluarga 10, BH q=0,10 | 2,58 | 230 | 459 |
| **keluarga 21 (D14), BH q=0,10** | **2,82** | **274** | **549** |

> **Konsekuensi keras:** dengan 360 hari histori SoDEX (maksimum 180 window),
> **mustahil** mengonfirmasi mesin kelas-target atas keluarga 21 di venue ini
> hari ini. Constraint = **panjang bukti**, bukan ide, bukan leverage.

Dua jalan keluar sah:
1. **Nasib window**: pakai SELURUH 180 window (portofolio lintas-seksi yang
   selalu di pasar), bukan 15–45 seperti mesin trade-diskrit. → +4–12× power,
   tanpa data baru. **Ini diuji pada §3.**
2. **Pinjam histori**: uji MEKANISME di panel panjang venue lain
   (Binance, ~5,5 tahun, 250 simbol) lalu **wajib replikasi** di SoDEX.

---

## 2. Kontrol kualitas yang WAJIB (dari PERINTAH_1_SoDEX.md)

1. Beta-netral: return forward di-demean lintas-seksi (setara dollar-neutral +
   market-neutral). Sisi long/short dilaporkan terpisah.
2. Biaya diuji **1× dan 2×** (SoDEX taker 4 bps/sisi → 8 bps round-trip).
3. **Kontrol negatif WAJIB**: sinyal diacak dalam baris (seed tetap), konstruksi
   identik. Kalau kontrol LOLOS → uji terlalu mudah.
4. Jendela < 6 bulan: sah untuk verifikasi eksekusi, **tidak sah** menilai alpha.
5. t-stat gabungan lintas aset **tidak dipakai** menyimpulkan (korelasi silang).
   → t dihitung pada **deret waktu portofolio** dengan Newey-West.
6. Dilarang menaikkan leverage; dilarang mengubah target; dilarang menyembunyikan
   trial yang gagal.

---

## 3. Keluarga hipotesis (DIBEKUKAN — 12 mekanisme × 2 hold = 24 trial)

Panel: Binance USDT-perp, top-250 volume, 1d, seluruh histori (~5,5 tahun).
Konstruksi: peringkat lintas-seksi → bobot dollar-neutral, Σ|w| = 1, rebalance
tiap `H` hari, hold `H` hari. Return portofolio = Σ wᵢ × (rᵢ − rata-rata r) − biaya.

| # | kode | sinyal (pada t) | tanda | dasar |
|---|---|---|---|---|
| 1 | REV_L1 | return 1 periode | − | reversal jangka pendek |
| 2 | REV_L3 | return 3 periode | − | reversal jangka pendek |
| 3 | REV_VOL | return / vol realisasi 20p | − | reversal ternormalisasi vol |
| 4 | REV_IDIO | residual vs pasar (β dari 60p) | − | reversal idiosinkratik |
| 5 | MOM_L21 | return 21 periode | + | momentum menengah |
| 6 | MOM_L63 | return 63 periode | + | momentum menengah |
| 7 | LTREV_L180 | return 180 periode | − | reversal jangka panjang |
| 8 | RANGEPOS | (close − low_N)/(high_N − low_N), N=20 | − | posisi dalam rentang |
| 9 | VOLSHOCK | z(volume 1p vs 20p) × tanda(return) | − | guncangan volume |
| 10 | MAXFX | rata-rata 5 return harian terbesar, 20p | − | efek lotre (Bali dkk.) |
| 11 | CARRY_FR | funding rate periode terakhir | − | long funding rendah / short tinggi |
| 12 | BASIS | (mark − index)/index | − | premi mark |

Hold: **H = 2 hari** (≈ window 48 jam target) dan **H = 5 hari**.

**Ambang lulus (per mesin):**
- Sharpe_ann bersih ≥ 2,3 (1× biaya) DAN tetap ≥ 1,8 pada 2× biaya;
- BH-FDR q = 0,10 atas **24 trial** (dua arah, p dua sisi);
- 3/3 segmen waktu positif (Σ|segmen| > 30 window tiap segmen);
- kontrol negatif TIDAK lulus (|t| < 2);
- **replikasi SoDEX**: tanda IC sama dan |IC_SoDEX| ≥ ½ |IC_Binance| pada panel
  99 simbol SoDEX (1d + 1h). Tanpa replikasi → ditandai `TIDAK-REPLIKASI`,
  tidak boleh dipakai mesin SoDEX (pelajaran H5: breakout berbalik arah
  antar-venue).

**Yang dihitung dan dilaporkan apa adanya:** setiap trial, lulus atau gagal,
termasuk yang buruk. `instrument_fpr` dicek lewat kontrol negatif.

---

## 4. Yang TIDAK dilakukan

- Tidak menyetel ulang ambang setelah melihat hasil.
- Tidak menghapus trial gagal dari registry.
- Tidak menaikkan leverage.
- Tidak mengubah target 0,8%/48 jam.
- Tidak menyimpulkan alpha dari window < 6 bulan.

---

## 5. Urutan eksekusi

1. `scripts/research/binance_pull_klines.py 1d 250` → panel panjang.
2. `scripts/research/xsec_mech_study.py --panel binance --hold 2,5` → 24 trial,
   BH, kontrol negatif. Output `reports/sodex/PRAREG_PANEL_PANJANG_HASIL.json`.
3. Replikasi SoDEX: `--panel sodex --hold 2,5`.
4. Laporan hasil; mesin yang lolos §3 masuk kandidat portofolio 6–8 mesin.

Dibekukan: 07-Okt-2026 · Divisi Riset Anantara Sakti
