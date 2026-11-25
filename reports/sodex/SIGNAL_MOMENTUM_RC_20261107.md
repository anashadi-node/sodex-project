# H5 — Apakah sinyal membeli setelah kenaikan (chase)?

n: SIGNAL 411, RANDOM 1404. Biaya 0.1pp. Split IS/OOS pada 2026-10-28 19:00Z.

## 1. Return PRA-entry: SIGNAL vs RANDOM (permille = %, tapi pp)

| jendela | SIGNAL mean | RANDOM mean | selisih | p (Mann-Whitney) |
|---|---|---|---|---|
| pre6 | +1.162 | -0.482 | +1.644 | 3.24e-83 |
| pre24 | +2.677 | -1.085 | +3.762 | 3.15e-121 |
| pre72 | +2.016 | -1.115 | +3.131 | 1.44e-42 |

## 2. Apakah kenaikan pra-entry memprediksi hasil NEGATIF? (dalam pair sama)

| jendela | Spearman (pooled) | Spearman (didalam pair, demean) | p | arah |
|---|---|---|---|---|
| pre6 | -0.052 (p=5.03e-03) | -0.041 (p=2.63e-02) | 2.63e-02 | PREDIKTIF NEGATIF |
| pre24 | -0.054 (p=3.72e-03) | -0.046 (p=1.43e-02) | 1.43e-02 | PREDIKTIF NEGATIF |
| pre72 | -0.137 (p=1.59e-13) | -0.119 (p=1.53e-10) | 1.53e-10 | PREDIKTIF NEGATIF |

## 3. Kandidat aturan (dipilih di IS, diukur di OOS) — SIGNAL saja

| aturan | side | hold | IS n | IS net | OOS n | OOS net | CI95 OOS | status |
|---|---|---|---|---|---|---|---|---|
| apa adanya | long | 4j | 287 | -0.334pp | 124 | -1.423pp | [-1.98,-0.86] | gagal |
| short apa adanya | short | 4j | 287 | +0.134pp | 124 | +1.223pp | [+0.66,+1.78] | LOLOS |
| short hanya pre24>0% | short | 4j | 266 | +0.140pp | 110 | +1.204pp | [+0.62,+1.79] | LOLOS |
| long hanya pre24<3% | long | 4j | 199 | -0.218pp | 87 | -1.405pp | [-1.99,-0.86] | gagal |
| short hanya pre24>3% | short | 4j | 88 | +0.397pp | 37 | +1.264pp | [-0.03,+2.50] | gagal |
| long hanya pre24<6% | long | 4j | 260 | -0.301pp | 107 | -1.483pp | [-2.02,-0.96] | gagal |
| short hanya pre24>6% | short | 4j | 27 | +0.454pp | 17 | +0.840pp | [-1.52,+2.84] | gagal |
| apa adanya | long | 24j | 287 | -1.057pp | 124 | -1.870pp | [-2.67,-1.08] | gagal |
| short apa adanya | short | 24j | 287 | +0.857pp | 124 | +1.670pp | [+0.88,+2.47] | LOLOS |
| short hanya pre24>0% | short | 24j | 266 | +0.881pp | 110 | +1.560pp | [+0.78,+2.36] | LOLOS |
| long hanya pre24<3% | long | 24j | 199 | -0.895pp | 87 | -1.816pp | [-2.76,-0.92] | gagal |
| short hanya pre24>3% | short | 24j | 88 | +1.225pp | 37 | +1.797pp | [+0.34,+3.29] | LOLOS |
| long hanya pre24<6% | long | 24j | 260 | -1.006pp | 107 | -1.668pp | [-2.51,-0.82] | gagal |
| short hanya pre24>6% | short | 24j | 27 | +1.356pp | 17 | +2.943pp | [+0.88,+4.90] | LOLOS |
| apa adanya | long | 48j | 287 | -1.515pp | 124 | -3.315pp | [-3.98,-2.63] | gagal |
| short apa adanya | short | 48j | 287 | +1.315pp | 124 | +3.115pp | [+2.43,+3.78] | LOLOS |
| short hanya pre24>0% | short | 48j | 266 | +1.361pp | 110 | +3.368pp | [+2.71,+4.06] | LOLOS |
| long hanya pre24<3% | long | 48j | 199 | -1.618pp | 87 | -3.035pp | [-3.85,-2.22] | gagal |
| short hanya pre24>3% | short | 48j | 88 | +1.080pp | 37 | +3.773pp | [+2.50,+5.14] | LOLOS |
| long hanya pre24<6% | long | 48j | 260 | -1.595pp | 107 | -3.021pp | [-3.70,-2.32] | gagal |
| short hanya pre24>6% | short | 48j | 27 | +0.537pp | 17 | +4.966pp | [+2.91,+7.14] | LOLOS |

## Kesimpulan

- Aturan yang lolos (net OOS ≥ +0,205pp dan CI95 bawah > 0): **10** dari 21 kandidat.
  - short apa adanya / short / 4j → OOS +1.223pp (CI95 [+0.66,+1.78], n=124)
  - short hanya pre24>0% / short / 4j → OOS +1.204pp (CI95 [+0.62,+1.79], n=110)
  - short apa adanya / short / 24j → OOS +1.670pp (CI95 [+0.88,+2.47], n=124)
  - short hanya pre24>0% / short / 24j → OOS +1.560pp (CI95 [+0.78,+2.36], n=110)
  - short hanya pre24>3% / short / 24j → OOS +1.797pp (CI95 [+0.34,+3.29], n=37)
  - short hanya pre24>6% / short / 24j → OOS +2.943pp (CI95 [+0.88,+4.90], n=17)
  - short apa adanya / short / 48j → OOS +3.115pp (CI95 [+2.43,+3.78], n=124)
  - short hanya pre24>0% / short / 48j → OOS +3.368pp (CI95 [+2.71,+4.06], n=110)
  - short hanya pre24>3% / short / 48j → OOS +3.773pp (CI95 [+2.50,+5.14], n=37)
  - short hanya pre24>6% / short / 48j → OOS +4.966pp (CI95 [+2.91,+7.14], n=17)
- Batas: angka ini close-to-close pada kline 1 jam; fill, slippage, dan funding perp belum dimodelkan di sini (biaya flat 0,10pp).
