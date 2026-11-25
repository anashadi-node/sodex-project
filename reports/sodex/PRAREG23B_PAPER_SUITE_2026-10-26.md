# PRAREG-23b — LAPORAN SUITE PAPER TEST (26-Okt-2026)

Dibuat: 2026-10-26T00:40:11Z · data s.d. 2026-10-24 · engine `6c86d693dfa27437` · target **M ≥ 0,010 %/5 jam** · DRY-RUN, tanpa modal berisiko.

Semua angka = backtest/paper pada data historis (in-sample untuk pemilihan desain). **Bukan bukti edge.**

## S1 — Matriks M (%/5 jam) per arm × biaya × periode

| Arm | Biaya/sisi | 2019+ | 2022+ | 2024+ | OOS 24-Mei-26+ |
|---|---|---:|---:|---:|---:|
| A | 0,07% (fee taker nyata) | 0.0157 | 0.0063 | 0.0086 | 0.0023 |
| A | 0,10% (primer) | 0.0155 | 0.0061 | 0.0084 | 0.0021 |
| A | 0,15% | 0.0152 | 0.0057 | 0.0081 | 0.0017 |
| A | 0,25% | 0.0146 | 0.0051 | 0.0074 | 0.0011 |
| B1 | 0,07% (fee taker nyata) | 0.0191 | 0.0120 | 0.0163 | -0.0061 |
| B1 | 0,10% (primer) | 0.0190 | 0.0118 | 0.0162 | -0.0063 |
| B1 | 0,15% | 0.0187 | 0.0116 | 0.0159 | -0.0066 |
| B1 | 0,25% | 0.0182 | 0.0110 | 0.0153 | -0.0072 |
| B2 | 0,07% (fee taker nyata) | 0.0175 | 0.0094 | 0.0138 | 0.0022 |
| B2 | 0,10% (primer) | 0.0172 | 0.0091 | 0.0135 | 0.0019 |
| B2 | 0,15% | 0.0168 | 0.0086 | 0.0130 | 0.0014 |
| B2 | 0,25% | 0.0159 | 0.0075 | 0.0120 | 0.0005 |

Target 0,010 tercapai (2022+, biaya primer): **A tidak (0,0061)**, **B2 tidak (0,0091)**, **B1 ya (0,0119)** — B1 rata-rata ±79% emas dan **−0,0063 di OOS 2026**; MDD B1 −27%.

## S2 — Sensitivitas arm A (2022+, biaya 0,10%) — M %/5j

| lag=0 | lag=1 | lag=2 | lag=3 | band=0.05 | band=0.1 | band=0.2 | band=0.3 | band=0.5 | VT=0.25 | VT=0.35 | VT=0.5 | VT=0.7 | VT=1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.00662 | 0.00606 | 0.0058 | 0.00542 | 0.00616 | 0.00616 | 0.00606 | 0.006 | 0.0069 | 0.0044 | 0.00531 | 0.00606 | 0.0056 | 0.00574 |

Tidak ada konfigurasi A mencapai 0,010. Rentang 0,0044–0,0069.

## S3 — Jendela bergulir 31 hari (2022+, 1.728 jendela, biaya 0,10%)

| Arm | M p10/p50/p90 | P(M31 ≥ 0,010) | P(cum<0) | P(G3) | P(G4) | P(G3&G4) | cum p05 |
|---|---|---:|---:|---:|---:|---:|---:|
| A | [-0.0203, -0.0014, 0.0468] | 28% | 54% | 100% | 98% | 98% | -3.92% |
| B1 | [-0.0329, 0.0107, 0.0625] | 51% | 39% | 94% | 90% | 88% | -6.44% |
| B2 | [-0.0224, 0.0023, 0.0518] | 40% | 48% | 98% | 96% | 95% | -4.41% |

Gerbang G3/G4 PRAREG-23b lolos di 98% jendela historis arm A → gerbang adalah **pembatas kerugian**, bukan uji target.

## S4 — Bootstrap blok 30 hari, tahun 365 hari (10.000×)

| Arm | M median | CI95 | P(M ≥ 0,010) | P(M<0) |
|---|---:|---|---:|---:|
| A | 0.00558 | [-0.0076, 0.02655] | 31% | 24% |
| B1 | 0.01257 | [-0.0089, 0.03595] | 59% | 13% |
| B2 | 0.00907 | [-0.00718, 0.03013] | 46% | 15% |

## S5 — Kontrol negatif (geser sirkular target A, 400×)

M nyata 0.00606 vs null rata-rata 0.00287 (p95 0.00673). **p empiris = 0.1022** → timing sinyal A **belum signifikan** di atas acak pada α=0,05 (ambang registry jauh lebih ketat). Sebagian besar M berasal dari eksposur long BTC/ETH, bukan timing.

## S6 — Eksekusi diskret $243,02 (minNotional $5, step nyata, fee 0,065% + 0,6 bps)

| Arm | M diskret | M ideal | selisih | order | dilewati | fee total | MDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0.00626 | 0.00626 | -1e-05 | 1265 | 1087 | $14.99 | -13.6% |
| B1 | 0.01169 | 0.01201 | -0.00032 | 749 | 1209 | $13.1 | -26.2% |
| B2 | 0.00924 | 0.0094 | -0.00016 | 1282 | 1118 | $26.08 | -19.2% |

Modal kecil **tidak** merusak hasil: selisih ≤ 0,0003 %/5j. Banyak order kecil di bawah $5 dilewati tanpa mengubah hasil.

## S7 — Ekor risiko (2022+)

| Arm | hari terburuk | 5 hari | 31 hari | MDD |
|---|---:|---:|---:|---:|
| A | -4.55% | -8.03% | -8.56% | -13.8% |
| B1 | -10.19% | -14.19% | -15.71% | -27.2% |
| B2 | -10.19% | -13.78% | -9.45% | -19.5% |

## S8 — Forward & mikrostruktur (snapshot saat suite dijalankan; terus bertambah)

Buku spot SoDEX nyata: btc spread 0.125 bps, biaya order $60 0.062 bps; eth spread 0.429 bps, biaya order $60 0.215 bps; xaut spread 0.501 bps, biaya order $60 0.251 bps. Biaya efektif per sisi ≈ **fee taker 6,5 bps + ≤0,25 bps** ≈ 0,07% (< asumsi primer 0,10%).

## Kesimpulan jujur

1. Target 0,01%/5 jam **tidak dicapai arm A** di skenario manapun (maks 0,0069); hanya B1 yang melewati lewat eksposur emas dengan MDD −27% dan hasil OOS 2026 negatif.
2. Peluang tahun kalender A mencapai target ≈31%; peluang tahun merugi ≈24%.
3. Eksekusi di modal $243 dan buku nyata **tidak** menjadi hambatan; biaya nyata lebih rendah dari asumsi.
4. Edge timing A belum terbukti (p=0,10 vs acak). Jendela forward 31 hari tidak mampu membuktikan apa pun tentang target.
