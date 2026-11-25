# PRAREG-37 — Upaya Menaikkan Reliabilitas (26-Okt-2026)

Tujuan: target 0,010 %/5j tetap, tapi **peluang mencapainya per jendela** harus naik tanpa melanggar MDD −35%. Lima hipotesis diuji; empat mati. Tidak ada sel/gate PRAREG-36 yang diubah.

## 1. Hasil lima hipotesis

| # | Hipotesis | Hasil (2022-01→2026-10) | Vonis |
|---|---|---|---|
| H1 | Sisi SHORT simetris (Donchian breakdown) | M 0,0137, MDD **−66,8%**, Sharpe 0,45 | **MATI** — short kripto di bull market menghancurkan ekuitas |
| H2 | Momentum lintas-koin 29 aset, long 5 | Train M 0,0158, **OOS −0,0026**, MDD −44,2% | **MATI** — hanya bekerja in-sample |
| H3 | Momentum lintas-koin long-short 5/5 | OOS −0,0044, MDD −42,0% | **MATI** |
| H4 | Carry delta-neutral (BTC/ETH) | Sharpe **13,3**, vol 0,019%/hari, tapi M **0,0027** | **TIDAK CUKUP** — perlu 3,7× modal untuk target; mustahil dengan margin 33% |
| H5 | Vol-target 25%, cap 2,5, floor 1,0 | M **0,0157**, MDD **−31,6%**, hit30 **43,8%** (train 40,2 / OOS 51,0) | **DIPAKAI (bayangan)** — p bootstrap 0,198 → bukan bukti |

Vol-target 30–45% semuanya menembus MDD (≤ −35,4%) → gagal plafon.

## 2. Koreksi yang saya temukan sendiri
Run pertama melaporkan varian vol-target 25% dengan M 0,0109 dan MDD −24,6%. **Salah**: vol portofolio dihitung dari sinyal simetris (H1), bukan dari sinyal B2 yang benar-benar ditransaksikan. Setelah diperbaiki: M **0,0157**, MDD **−31,6%**. Angka lama dibatalkan, bukan “dipilih yang bagus”.

## 3. Dekomposisi alpha/beta (regresi return harian vs BTC, 2022-2026)
| Besaran | Nilai |
|---|---|
| Beta BTC | 0,302 |
| Korelasi | 0,574 |
| **Alpha** | **0,00966 %/5j** |
| t-alpha | 1,71 (tidak signifikan) |

Alpha berdiri sendiri **sedikit di bawah target 0,010**; sisa 0,0042 %/5j berasal dari beta pasar. Jadi target terpenuhi sebagai **alpha + beta**, bukan alpha murni. Ini alasan tambahan untuk tidak mengklaim edge tanpa beta.

## 4. Batas matematis yang tidak bisa dilangkahi
Target 0,010 %/5j = **0,048 %/hari** ≈ 17,5 %/tahun. Varian terbaik menghasilkan 0,075 %/hari (27,5 %/tahun) dengan vol 26 %/tahun → Sharpe ≈ 1,05.

Peluang satu jendela mencapai target (historis, 1.729 jendela):

| Horizon | Baseline 1,5× | Varian vol-target | n |
|---|---|---|---|
| 30 hari | 40,5% | **43,8%** | 1.729 |
| 60 hari | 42,4% | 47,0% | 1.699 |
| 90 hari | 48,6% | **53,1%** | 1.669 |
| 180 hari | 53,6% | 60,4% | 1.579 |
| 365 hari | 63,4% | **70,4%** | 1.394 |

Artinya: **reliabilitas adalah masalah horizon, bukan masalah sinyal.** Pada 30 hari, bahkan strategi dengan mean 1,57× target hanya menang ~44% waktu, karena sd 30-hari ≈ 7,6% sedangkan target hanya 1,44%.

## 5. Keputusan
- **PRAREG-36 tidak diubah.** Sel B2 1,5× dan A 2,0× tetap beku sampai 25-Nov.
- **PRAREG-37 = bayangan** (tanpa order, tanpa modal): mencatat varian vol-target harian, evaluasi **90 hari → 24-Jan-2027**. Tujuannya membandingkan alokasi risiko pada data forward, bukan menguji hipotesis baru.
- **Untuk GO live 01-Des**: keputusan harus berbasis anggaran risiko, bukan p-value. Angka yang tersedia: M historis 1,57× target, MDD −31,6%, hit30 44%, hit90 53%, hit365 70%.
- Klaim yang **tidak** boleh dibuat: “varian ini lebih baik” (p=0,198), “target terjamin” (44% per 30 hari), “live aman” (eksekutor live belum ada).

## 6. Batas
- Universe H2/H3: koin yang masih ada → survivorship bias, hasil = batas atas.
- Carry: basis diasumsikan konstan; funding Binance sebagai proksi SoDEX.
- Likuidasi dihitung dari penutupan, bukan low intraday.
- Vol-target memakai vol 20-hari eks-ante (tanpa lookahead), tetapi rebalancing harian mengasumsikan eksekusi di penutupan.
