# SODEX Proxy Lab — Fidelity Binance↔SoDEX & Daya Prediksi Histori Panjang

**Tanggal:** 06-Okt-2026 · **Skrip:** `scripts/sodex_proxy_lab.py` · **Mode:** READ-ONLY, tanpa jalur order, tanpa menyentuh F1/lockbox (data ≥2026-09-01 tidak dipakai).
**Spesifikasi ditulis sebelum menjalankan** (docstring skrip). Hipotesis F1 tidak diubah oleh dokumen ini; ini hanya penyedia *prior*.

## Tes 1 — apakah harga Binance bisa mewakili harga SoDEX?

BTC/ETH/SOL, tape SoDEX nyata vs Binance USDM 1 jam, 2026-06-01..08-31 (2.017 jam per simbol):

| Simbol | Korelasi return 1 jam | Selisih level median / p95 | Bar "gerak ≥1,5%" (SoDEX/Binance) | Jaccard |
|---|---|---|---|---|
| BTC | **0,9993** | 0,1 bp / 1,7 bp | 32 / 33 | 0,97 |
| ETH | **0,9989** | 0,4 bp / 3,8 bp | 61 / 61 | 1,00 |
| SOL | **0,9978** | 1,3 bp / 6,1 bp | 83 / 87 | 0,91 |

**Kesimpulan:** Binance/HL **layak** dipakai sebagai proksi arah/gerakan harga SoDEX untuk BTC/ETH/SOL (bukan sebagai bukti final, karena bukti final tetap harus dari tape SoDEX).

## Tes 2 — momentum 1 jam di 14 simbol, 16 bulan (proksi Binance)

Grid beku: θ ∈ {2, 3, 4, 5}% × arah {momentum, fade} = 8 uji; BH-FDR q=0,10. Masuk OPEN bar berikutnya (tanpa look-ahead), tahan 24 jam, biaya 24 bp, klaster 24 bar, p = sign-flip level hari.

| θ | Arah | Split | n | Rata-rata | WR | p_hari | BH |
|---|---|---|---|---|---|---|---|
| 2% | momentum | DEV | 821 | −0,051% | 45,8% | 0,569 | — |
| 2% | momentum | OOS | 969 | +0,005% | 49,2% | 0,491 | — |
| 3% | momentum | DEV | 327 | +0,536% | 52,0% | 0,173 | — |
| 3% | momentum | **OOS** | 426 | **−0,151%** | 45,5% | 0,618 | — |
| 4% | momentum | DEV | 130 | +0,946% | 52,3% | 0,179 | — |
| 4% | momentum | **OOS** | 197 | **−0,411%** | 45,2% | 0,714 | — |
| 5% | momentum | DEV | 55 | +1,171% | 52,7% | 0,190 | — |
| 5% | momentum | **OOS** | 95 | **+0,392%** | 45,3% | 0,364 | — |

**0 dari 8 uji lolos BH-FDR.** Semua arah fade jauh negatif (konsisten: melanjutkan gerakan lebih baik daripada melawannya, tetapi tetap tidak cukup untuk mengalahkan biaya).

## Yang benar-benar diberitahukan hasil ini

1. **Sinyal "beli setelah gerakan besar" tidak punya edge tahan-lama** di 14 simbol pasar besar: positif di DEV, lalu **runtuh di OOS** (θ=3%: +0,54% → −0,15%; θ=4%: +0,95% → −0,41%). Pola DEV→OOS inilah yang dulu membuat 41 evaluasi gagal.
2. **Namun ini uji 1 jam**, sedangkan F1 menguji event **2% dalam 15 menit lalu tahan 24 jam**. Detail penting: proksi 1 jam **tidak dapat menyelesaikan** perbedaan itu, sebagian karena θ yang sama pada bar 1 jam jauh lebih jarang (n=821 vs n≈68 pada tape SoDEX 20 simbol).
3. **Prior untuk F1 harus diturunkan, dan itu ditulis di sini sebelum hasil F1 keluar**: peluang lulus C0–C8 yang semula saya taksir ≤25% kini saya taksir **≤15%**. Ini tidak mengubah kriteria F1 (beku).
4. **Pelajaran arah kerja:** keunggulan SoDEX tidak akan datang dari meniru sinyal pasar besar. Kandidat yang lebih masuk akal: struktur mikro venue SoDEX sendiri (spread/OBI, kedalaman, imbalance), perbedaan funding, dan efek likuidasi — semuanya harus diuji pada **tape SoDEX**, bukan proksi.

## Batas kejujuran

- Hasil OOS θ=5% (+0,392%, n=95, p=0,364) **tidak signifikan**; jangan dibaca sebagai "momentum besar berhasil".
- Biaya 24 bp bersifat asumsi konservatif; spread nyata SoDEX untuk 17 simbol alt belum diukur.
- Kesimpulan "proksi layak" hanya berlaku untuk BTC/ETH/SOL; 6 simbol SoDEX (PONS, QNT, SNDK, SPCX, US500, XAUT) tidak ada di Binance/HL.

## Perintah

```
.venv-research/bin/python3 scripts/sodex_proxy_lab.py
```
