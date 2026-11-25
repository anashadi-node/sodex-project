# DIAGNOSIS ETH / ASTER / SUI — kenapa alpha negatif

Tanggal: 31-Okt-2026 · Sumber `reports/sodex/PRAREG40_SETTLED.jsonl` (n=1.690)
Alat: `scripts/diag_symbol.py` (dekomposisi raw / beta / fee per track, sisi, jam, hold).

## 1. ETH — bukan noise, bukan bug biaya
n=128 · alpha_net **−0,567%** · t = **−7,06** · alpha>0 hanya 26,6%.

| Komponen | Nilai |
|---|---|
| mean raw (ETH sendiri) | −0,293% |
| mean beta×BTC | +0,195% |
| alpha_gross | −0,487% |
| fee 8 bps | −0,080% |

Artinya: ETH **turun** saat BTC **naik**. Kerugian bukan dari spread/fee (hanya 8 bps),
bukan dari satu track — negatif di **12 dari 13 track**, di **long maupun short**,
dan di **semua bucket hold**. Yang paling buruk: entry 06–11h (−0,898%, t=−5,01)
dan 12–17h (−0,831%, t=−5,71).

## 2. ASTER & SUI — pola sama, arah sama
| Simbol | n | alpha_net | t | komposisi | raw | beta×BTC |
|---|---|---|---|---|---|---|
| ASTER | 59 | −0,646% | −2,82 | 56 long / 3 short | −0,542% | +0,024% |
| SUI | 51 | −0,574% | −1,63 | **51 long / 0 short** | −0,325% | +0,169% |

Ketiganya: **long alt yang tertinggal dari BTC**, bukan kesalahan eksekusi.

## 3. Temuan yang lebih besar: buku ini 87% long
| Kelompok | n | alpha_net | t |
|---|---|---|---|
| LONG (semua) | 1.462 | **−0,160%** | **−2,73** |
| SHORT (semua) | 228 | +0,015% | +0,22 |

Sisi × jam entry (UTC):

| Sel | n | alpha_net | t |
|---|---|---|---|
| LONG 00–05h | 366 | −0,533% | −5,21 |
| LONG 06–11h | 368 | −0,261% | −2,35 |
| **LONG 12–17h** | 414 | **+0,366%** | **+2,79** |
| LONG 18–23h | 314 | −0,300% | −2,75 |
| **SHORT 00–05h** | 97 | **+0,268%** | **+4,10** |
| SHORT 18–23h | 37 | −0,413% | −2,32 |

Dua sel positif besar: **long siang Eropa/US (12–17h)** dan **short dini hari (00–05h)**.
Sisanya negatif. Ini menjelaskan kenapa gate per-simbol hanya mengurangi pendarahan:
masalah utamanya **arah + jam**, bukan cuma simbol.

## 4. Kejujuran statistik
- 8 sel diuji; BH q=0,05 → ambang sel terkecil 0,00625. `t=2,79` (p≈0,0053) **lolos
  marginal**; `t=4,10` dan `t=−5,21` lolos jelas.
- Tetapi semua ini **in-sample**. Tanpa uji forward, ini kandidat — bukan bukti.
- Karena itu PRAREG-41 (blocklist) dibekukan lebih dulu, dan temuan jam/sisi ini
  diusulkan sebagai **PRAREG-42** yang belum dibekukan.

## 5. Rekomendasi
1. **PRAREG-41** (sudah beku, overlay 06:50): buang ETH/ASTER/SUI, uji forward 01–30 Nov.
2. **PRAREG-42** (usulan, belum beku): long hanya 12–17h, short hanya 00–05h.
   Gerbang sama + G7 kontrol negatif (jam acak dengan porsi setara harus gagal).
3. Jangan menyentuh PRAREG-23b/26/36/40. Semua ini overlay paper, tanpa order.
