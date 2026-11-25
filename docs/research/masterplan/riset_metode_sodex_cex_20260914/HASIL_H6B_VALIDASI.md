# VALIDASI H6b — Momentum Harian: KOREKSI PENTING
**Dijalankan 14 Sep 2026 · 30 simbol · biaya fee 9 bps RT + funding nyata · walk-forward**

## KOREKSI TERHADAP KESIMPULAN H6 SEBELUMNYA

Di HASIL_H6.md saya menandai momentum harian sebagai **PROMISING** berdasarkan
t-statistik gabungan **t = +4,30** (n=8.917). **Validasi ini MEMBATALKAN kesimpulan itu.**

## Hasil validasi

```text
AGREGAT
  simbol                               : 30
  gross (rata-rata simbol)             : ~+15 bps/hari
  biaya funding (rata-rata)            : 0,53 bps/hari   ← KECIL (posisi flip L/S, saling hapus)
  fee round-trip diasumsikan           : 9,0 bps
  net (rata-rata simbol)               : +3,56 bps
  net (tertimbang hari)                : +6,42 bps
  median net per simbol                : +5,11 bps
  simbol dengan net > 0                : 60,0%
  simbol positif di KEDUA paruh waktu  : 46,7%   ← coin flip
  MEDIAN t-statistik per simbol        : 0,30    ← hampir nol
  simbol dengan |t| > 2                : 0 dari 30  ← TIDAK ADA SATUPUN
  mean funding rate 8 jam              : 0,00356%
```

### Sebaran per simbol (bukti dispersi = noise, bukan edge)

```text
  UNI     +58,06 bps  t=1,88  h1=+25,7  h2=+90,1
  ARB     +33,69 bps  t=1,50  h1=+60,2  h2= +7,3
  ADA     +27,89 bps  t=1,61  h1=+33,5  h2=+22,3
  ...
  ZEC     +15,98 bps  t=0,33  h1=+122,3 h2=−89,3   ← tidak stabil
  SOL      +0,41 bps  t=0,03  h1=−17,4  h2=+18,1   ← tanda berbalik
  BTC      −5,25 bps  t=−0,56 h1=−11,1  h2= +0,6
  ASTER   −42,82 bps  t=−1,42 h1=−36,0  h2=−49,7
  PENDLE  −38,34 bps  t=−1,17 h1=−59,9  h2=−17,0
  HYPE    −39,46 bps  t=−1,29 h1=−25,8  h2=−53,0
```

## Diagnostik: mengapa t gabungan menyesatkan

```text
1. Return kripto sangat BERKORELASI LINTAS SIMBOL (satu faktor pasar).
   Menggabungkan 30 simbol menjadi 8.917 observasi "independen" adalah
   kekeliruan — observasi tidak independen.
2. Koreksi yang benar: standard error terklaster (per hari) atau regresi panel
   dengan fixed effect waktu. t=4,30 hampir pasti menyusut drastis.
3. Bukti langsung: MEDIAN t per simbol = 0,30 dan NOL simbol signifikan.
   Jika edge nyata dan kuat, sebagian besar simbol harusnya menunjukkan t > 1.
4. Uji stabilitas: hanya 46,7% simbol positif di kedua paruh → tidak ada
   persistensi. Edge yang nyata harus bertahan lintas periode.
```

**→ H6b: PROMISING dinyatakan DIBATALKAN. Status baru: INCONCLUSIVE / TIDAK ROBUST.**

## Yang TETAP berlaku dari H6

```text
✅ FALSIFIED  : mean-reversion 1h–1d mengalahkan biaya (edge gross ~0,3 bps vs biaya 9 bps)
✅ TERUKUR    : biaya funding perp TIDAK besar untuk strategi flip L/S (0,53 bps/hari rata-rata)
               → funding bukan pembunuh utama; fee/spread jauh lebih dominan (9 bps RT)
✅ PELAJARAN  : t-statistik gabungan lintas aset berkorelasi TIDAK VALID.
               Wajib: per-simbol + clustered SE + walk-forward stability.
```

## Mengapa ini penting untuk mandat 0,8%/30 jam

```text
Kesimpulan yang BERUBAH:
  SEBELUM: "momentum harian punya edge +18,9 bps/hari, arah baru!"
  SESUDAH: "tidak ada bukti edge momentum harian yang robust. Angka gabungan
            adalah artefak korelasi silang."

Konsekuensi: jalur "cari sinyal arah baru" untuk CEX TIDAK mendapat dukungan dari uji ini.
Yang tersisa dan TERBUKTI berdiri adalah temuan H1:
  → masalah utama bukan sinyal, melainkan CAPTURE terhadap favorable excursion
    (median MFE +1,087R vs median realized −0,125R, n=732).
```

## Catatan metodologis untuk seluruh riset ini

Uji ini adalah contoh mengapa **gate kualitas statistik wajib** (P23 MinervaScore/DSR/PBO,
P24 uji overfit DRL, standar P07 walk-forward + naive baseline + Diebold-Mariano):
tanpa gate, angka t=4,30 akan lolos menjadi "temuan" dan berpotensi menggerakkan modal.

**Label akhir H6:**
```text
H6a mean-reversion         : FALSIFIED
H6b momentum harian        : INCONCLUSIVE / tidak robust (koreksi dari PROMISING)
```
