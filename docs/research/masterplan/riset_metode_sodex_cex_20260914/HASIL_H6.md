# TEMUAN EMPIRIS H6 — Mean-Reversion vs Momentum lintas horizon
**Dijalankan 14 Sep 2026 · 30 simbol Binance USDM · data 1h/4h/1d · read-only**

## Desain uji
```text
Kontrarian: signal[i] = −sign(r[i]) ; hasil = signal[i] × Σ r[i+1 .. i+h]   (TANPA look-ahead)
Momentum  : kebalikan tanda dari kontrarian.
Biaya acuan: taker round-trip 9,0 bps · maker round-trip 4,0 bps (Binance USDM)
```
**Catatan disiplin:** versi pertama uji ini mengandung bug look-ahead (forward window
menyertakan bar sinyal) dan menghasilkan t=−444 — artefak yang jelas tidak wajar.
Bug ditemukan lewat inspeksi magnitudo, diperbaiki, dan tabel di bawah adalah hasil bersih.

## Hasil bersih

| Skenario | n | Kontrarian (gross bps) | t | Hit% | AC1 | VR | Net taker | Net maker |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1h, tahan 1 bar | 275.323 | **+0,277** | 1,63 | 50,3 | −0,0030 | 1,000 | −8,72 | −3,72 |
| 4h, tahan 1 bar | 68.753 | **−2,078** | −3,11 | 50,6 | +0,0135 | 1,000 | −11,08 | −6,08 |
| 1d, tahan 1 bar | 8.917 | **−18,945** | −4,30 | 48,7 | +0,0262 | 1,000 | −27,95 | −22,95 |
| 1h, tahan 4 bar | 275.233 | +0,560 | 1,67 | 50,1 | −0,0030 | 0,982 | −8,44 | −3,44 |
| 1h, tahan 24 bar | 274.633 | −1,196 | −1,44 | 49,6 | −0,0030 | 0,997 | −10,20 | −5,20 |

## Interpretasi

### 1) Mean-reversion jangka pendek: NYATA tapi TIDAK LAYAK DIPERDAGANGKAN
```text
1h: AC1 = −0,0030 (reversi lemah), VR = 1,000
    edge kontrarian gross = +0,277 bps, t=1,63 → TIDAK signifikan pada α=5%
    net setelah biaya: −8,7 bps (taker) / −3,7 bps (maker)
→ Sesuai P03 (mean-reversion 15-menit Binance: 90% pair signifikan, gross 1,3bp vs biaya 5bp).
  Kita mereplikasi temuan itu di horizon 1 jam: efeknya nyata tapi mati oleh biaya.
```

### 2) ✦ TEMUAN UTAMA — pada 4h dan 1d, tandanya TERBALIK: MOMENTUM

```text
4h momentum gross = +2,078 bps/bar   (t = +3,11 ; AC1 = +0,0135)
1d momentum gross = +18,945 bps/hari (t = +4,30 ; AC1 = +0,0262)
```

**Momentum harian adalah SATU-SATUNYA skenario yang lolos biaya:**

| Skenario momentum | gross bps | net taker (−9) | net maker (−4) | Lolos? |
|---|---:|---:|---:|---|
| 1h tahan 1 | −0,277 | −9,28 | −4,28 | ❌ |
| 4h tahan 1 | +2,078 | −6,92 | −1,92 | ❌ |
| **1d tahan 1** | **+18,945** | **+9,95** | **+14,95** | ✅ |
| 1h tahan 24 | +1,196 | −7,80 | −2,80 | ❌ |

**Kesimpulan H6:**
```text
H6a (mean-reversion 1-30 jam mengalahkan biaya) : FALSIFIED
H6b (momentum harian mengalahkan biaya)         : PROMISING — perlu validasi ketat
```

## Dukungan literatur independen
**P06 (arXiv 2602.11708)** — AdaptiveTrend: *trend-following 6-JAM* + portofolio adaptif +
trailing stop kalibrasi volatilitas + alokasi 70/30 → **Sharpe 2,41, MaxDD −12,7%, Calmar 3,18**
(150+ pair, 36 bulan OOS). Ini keluarga sinyal yang **sama arah** dengan temuan H6b, dan
memberi blueprint parameter (horizon 6 jam–harian, trailing stop, alokasi adaptif).

## CAVEAT WAJIB (belum boleh dipakai untuk keputusan modal)
```text
1. Uji naif: masuk di close, keluar di close. Belum ada slippage, spread, atau
   dampak pasar — biaya hanya angka tetap.
2. Belum ada biaya FUNDING (posisi perp ditahan semalam → funding bisa signifikan).
3. Belum dipecah per regime — hasil bisa didominasi periode 2025-2026 yang trending.
   Momentum harian punya risiko "momentum crash" yang terdokumentasi.
4. Belum ada Purged/Embargo CV → t-statistik belum dikoreksi untuk dependensi serial.
5. Belum diuji lintas sub-periode (walk-forward) maupun lintas simbol secara terpisah.
6. Multiple testing: 5 skenario diuji → ambang Bonferroni α=0,01 → t>2,58.
   t=4,30 lolos; t=3,11 lolos; keduanya masih perlu uji stabilitas.
```

## Implikasi untuk mandat 0,8% / 30 jam

```text
ARAH BARU YANG PENTING:
  • Bobot riset bergeser dari "cari sinyal reversal" ke "eksploitasi momentum 4h–1d
    dengan manajemen exit yang benar" — dan H1 sudah menunjukkan masalah kita ada di exit.
  • 4h→1d momentum + bracket exit (H1) = kombinasi dua temuan yang saling melengkapi:
      sinyal: momentum horizon menengah
      eksekusi: tangkap favorable excursion secara mekanis
  • Ini juga MENJELASKAN mengapa trade kita bisa punya median MFE +1,09R:
    sinyal kita memang membawa harga ke arah yang benar, tapi tanpa capture mekanis.

LANGKAH VALIDASI BERIKUT (wajib sebelum rekomendasi):
  V1. Momentum harian per-simbol + walk-forward + regime split (trending vs chop)
  V2. Tambahkan biaya funding nyata (data funding 1h tersedia, 30 simbol)
  V3. Purged/embargo CV, Deflated Sharpe / PBO sebagai gate kualitas
  V4. Uji kombinasi: sinyal momentum 4h/1d + kebijakan exit H1 (ladder/trailing)
```

**Label akhir H6: mean-reversion FALSIFIED; momentum 4h–1d PROMISING (belum tervalidasi ketat).**

> ⚠️ **KOREKSI 14 Sep (lihat HASIL_H6B_VALIDASI.md):** label "PROMISING" untuk momentum harian
> **DIBATALKAN** setelah validasi ketat. Median t-statistik per simbol = 0,30, **0 dari 30 simbol**
> memiliki |t| > 2, dan hanya 46,7% simbol positif di kedua paruh waktu. Angka t gabungan +4,30
> adalah **artefak korelasi silang antar aset** (observasi tidak independen). Status baru:
> **INCONCLUSIVE / tidak robust.** Yang tetap berdiri: H6a FALSIFIED, dan biaya funding
> terukur kecil (0,53 bps/hari) sedangkan fee 9 bps RT dominan.
