# Uji balik sinyal (2026-11-07)

n entry berpasangan kline: **3076**

## 1. Matched pair × minggu (confound pair/waktu dihapus)

| horizon | sel (pair×minggu) | entry S/R | Δ dalam sel | CI95 Δ | p |
|---|---|---|---|---|---|
| 4j | 94 | 456/1481 | -0.553pp | [-0.87,-0.24] | 0.0005 |
| 12j | 94 | 456/1481 | -0.613pp | [-0.98,-0.23] | 0.0010 |
| 24j | 94 | 456/1481 | -1.501pp | [-1.96,-1.05] | 0.0000 |
| 48j | 94 | 456/1481 | -1.707pp | [-2.41,-0.98] | 0.0000 |
| 72j | 94 | 456/1481 | -2.340pp | [-2.94,-1.76] | 0.0000 |

BH-FDR: matched_h4 q=0.0006, matched_h12 q=0.0010, matched_h24 q=0.0000, matched_h48 q=0.0000, matched_h72 q=0.0000

## 2. Flip walk-forward (70% IS menetapkan arah, 30% OOS sebagai bukti)

| horizon | IS mean sinyal | IS mean flipped | OOS n | OOS flipped net | CI95 | p (satu sisi) |
|---|---|---|---|---|---|---|
| 4j | -0.495pp | +0.495pp | 139 | +0.144pp | [-0.14,+0.44] | 0.1621 |
| 12j | -0.532pp | +0.532pp | 139 | +0.216pp | [-0.20,+0.64] | 0.1528 |
| 24j | -1.398pp | +1.398pp | 139 | +1.124pp | [+0.40,+1.86] | 0.0013 |
| 48j | -1.679pp | +1.679pp | 139 | +3.427pp | [+2.81,+4.03] | 0.0000 |
| 72j | -2.910pp | +2.910pp | 139 | +3.471pp | [+2.78,+4.16] | 0.0000 |

**Kesimpulan uji flip:** horizon yang lolos (CI95>0 dan p<0,05 di OOS): flip_h24, flip_h48, flip_h72.

Ambang roster uang nyata tetap net ≥ +0,205pp dengan batas bawah CI95 > 0; uji ini memakai biaya 0,10pp + funding 0,01%/8 jam dan belum memasukkan slippage/impact atau risiko reversal.
