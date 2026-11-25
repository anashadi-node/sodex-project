# Entry edge per horizon (BUKTI, 2026-11-07)

Entry unik: **3076** (SIGNAL 463 / RANDOM 2613); duplikat lintas lane dibuang 197.

Sumber: ledger lane paper + kline Binance 1h (cache replay). Return close-to-close relatif entry, arah sudah diterapkan. Biaya 0,10pp dikurangi pada kolom NET.

| horizon | n | NET rata2 | NET median | WR | MFE rata2 | MAE rata2 | MFE/|MAE| |
|---|---|---|---|---|---|---|---|
| 4j | 3069 | -0.052pp | -0.076pp | 47.1% | +1.35pp | -1.22pp | 1.11 |
| 4j SIGNAL−RANDOM | 463 vs 2606 | Δ -0.640pp | SIGNAL -0.595 | RANDOM +0.045 | WR S 38.9% / R 48.6% | p=0.0000 | | |
| 12j | 3069 | -0.019pp | -0.115pp | 47.6% | +2.34pp | -2.06pp | 1.14 |
| 12j SIGNAL−RANDOM | 463 vs 2606 | Δ -0.746pp | SIGNAL -0.652 | RANDOM +0.094 | WR S 43.6% / R 48.3% | p=0.0000 | | |
| 24j | 3069 | -0.104pp | -0.243pp | 46.8% | +3.26pp | -2.99pp | 1.09 |
| 24j SIGNAL−RANDOM | 463 vs 2606 | Δ -1.698pp | SIGNAL -1.546 | RANDOM +0.152 | WR S 33.7% / R 49.1% | p=0.0000 | | |
| 48j | 3069 | -0.387pp | -0.736pp | 40.0% | +4.49pp | -4.41pp | 1.02 |
| 48j SIGNAL−RANDOM | 463 vs 2606 | Δ -2.446pp | SIGNAL -2.463 | RANDOM -0.018 | WR S 23.8% / R 42.9% | p=0.0000 | | |
| 72j | 3069 | -0.612pp | -1.067pp | 38.6% | +5.42pp | -5.50pp | 0.98 |
| 72j SIGNAL−RANDOM | 463 vs 2606 | Δ -3.246pp | SIGNAL -3.369 | RANDOM -0.122 | WR S 23.1% / R 41.3% | p=0.0000 | | |

## Satu sisi + BH-FDR

| hipotesis | n | efek | p | q(BH) |
|---|---|---|---|---|
| delta_h72 | 3069 | -3.246pp | 0.0000 | 0.0000 |
| delta_h48 | 3069 | -2.446pp | 0.0000 | 0.0000 |
| delta_h24 | 3069 | -1.698pp | 0.0000 | 0.0000 |
| delta_h4 | 3069 | -0.640pp | 0.0000 | 0.0000 |
| delta_h12 | 3069 | -0.746pp | 0.0000 | 0.0000 |
| all_h12 | 3069 | -0.019pp | 0.6253 | 1.0000 |
| all_h4 | 3069 | -0.052pp | 0.8872 | 1.0000 |
| all_h24 | 3069 | -0.104pp | 0.9010 | 1.0000 |
| all_h48 | 3069 | -0.387pp | 0.9998 | 1.0000 |
| all_h72 | 3069 | -0.612pp | 1.0000 | 1.0000 |
