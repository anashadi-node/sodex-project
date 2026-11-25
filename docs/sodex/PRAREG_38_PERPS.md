# PRAREG-38 — Perps SoDEX + Leverage (26-Okt-2026)

Desain dibekukan sebelum run (`PRAREG_38_BEKU`, sha256 `e0ccbf41…`), satu amandemen pra-hasil (XAUT low dari PAXG). Sel dan gerbang tidak diubah setelah hasil.

## 1. Fakta venue (dokumen resmi + `bin/sodex markets perps`)
| Item | Nilai |
|---|---|
| Fee perp | taker **4,0 bps**, maker **1,2 bps** |
| Fee spot | taker **6,5 bps**, maker 3,5 bps |
| Funding | dibayar **tiap jam**; bunga tetap 0,03%/hari = **3,0 bps/hari** |
| MMR | 50% margin awal pada leverage maks → BTC/ETH **1,25%**, XAUT 2,0% |
| minNotional | $10 (BTC step 0,00001; ETH/XAUT 0,0001) |
| Leverage maks | BTC/ETH 40×, XAUT 25× (dipakai ≤3×) |

Koreksi penting: asumsi lama saya 10 bps/sisi dan funding 1,79 bps/hari **salah** untuk SoDEX. Biaya sebenarnya lebih rendah, funding lebih tinggi.

## 2. Model modal yang konsisten
`E = spot S + margin perp M`, notional perp `= M × Lp`, gross `= S + M×Lp`. Return dihitung terhadap E — bukan leverage di atas kertas. Liquidasi isolated memakai **low intraday**: `|low/prev−1| ≥ 1/Lp − MMR`.

## 3. Hasil (2022-01→2026-10, biaya taker, funding 3,0 bps/hari)
| Sel | Gross | M %/5j | MDD | Likuidasi | hit30 | Sharpe | Train | OOS |
|---|---|---|---|---|---|---|---|---|
| **P1 (utama)** | 1,50 | **0,01285** | −30,3% | **0** | 37,8% | 0,86 | 0,01286 | 0,01284 |
| P2 | 1,80 | 0,01447 | **−35,8%** | 0 | 38,1% | 0,81 | 0,01454 | 0,01435 |
| P3 | 1,15 | 0,01073 | −23,6% | 0 | 37,0% | 0,94 | 0,01068 | 0,01081 |
| P4 (vol-target) | 1,50 | 0,02281 | **−40,6%** | 0 | 42,8% | 1,01 | 0,02114 | 0,02558 |

Sensitivitas P1: funding Binance 1,79 → 0,01391 · funding stres 4,5 → **0,01154** · maker → 0,01339. Semua tetap di atas target.

## 4. Gerbang
| Gerbang | Ambang | P1 | Vonis |
|---|---|---|---|
| G1 M | ≥ 0,010 | 0,01285 | LOLOS |
| G2 MDD | ≥ −35% | −30,3% | LOLOS |
| G3 likuidasi | 0 | 0 | LOLOS |
| G4 > spot | > 0,00606 | 0,01285 | LOLOS |
| G5 funding stres | ≥ 0,008 | 0,01154 | LOLOS |
| G6 signifikansi | p ≤ 0,0125 | lihat §5 | **TIDAK LOLOS** |

## 5. Yang tidak boleh diklaim
- `p(M ≤ 0) = 0,0197` → expectancy positif **signifikan** (tipis).
- `p(M ≤ 0,010) = **0,3215**` → **target belum terbukti**. CI95 mean harian [0,0029%, 0,1262%] → per 5 jam [0,0006%, 0,0263%], mencakup target.
- Jadi P1 = `LAYAK_PAPER_BUKAN_BUKTI`, sama seperti PRAREG-35. P2 dan P4 gagal plafon MDD.

## 6. Keputusan
- **Paper perps mulai 27-Okt-2026** (P1), eksekutor paper dengan spesifikasi venue nyata.
- **Live perps 01-Des**: P1 dengan gross ≤1,5×, Lp=3, MMR nyata, margin buffer 20%, circuit breaker −15% dari puncak; naik hanya setelah eksekutor lolos selftest testnet.
- Batas live: modal perp ≤ $150 dari total ≤ $300; likuidasi harus ≥ 40% jauhnya saat entry (stress 3× vol harian).
