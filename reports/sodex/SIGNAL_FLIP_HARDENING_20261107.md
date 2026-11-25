# Hardening temuan "sinyal terbalik" (2026-11-07)

SIGNAL entries dengan kline: **463**

Semua angka = NET biaya (0,10pp + funding 0,01%/8 jam) dari arah TERBALIK (flip). CI95 = bootstrap blok per (pair, hari).

| horizon | n | dedupe keras n | flip net | CI95 cluster | p cluster | |CI jujur| vs 0 | biaya tahan |
|---|---|---|---|---|---|---|---|---|
| 4j | 463 | 255 | +0.495pp | [+0.213,+0.769] | 0.0003 | LOLOS | +0.213pp |
| 12j | 463 | 255 | +0.657pp | [+0.334,+0.985] | 0.0001 | LOLOS | +0.334pp |
| 24j | 463 | 255 | +1.430pp | [+0.957,+1.896] | 0.0000 | LOLOS | +0.957pp |
| 48j | 463 | 255 | +2.146pp | [+1.608,+2.658] | 0.0000 | LOLOS | +1.608pp |
| 72j | 463 | 255 | +3.006pp | [+2.445,+3.583] | 0.0000 | LOLOS | +2.445pp |

## Rincian per horizon (dedupe keras + cluster)

| horizon | paruh-1 | paruh-2 | LONG | SHORT |
|---|---|---|---|---|
| 4j | +0.321pp | +0.668pp | 0.495pp | - |
| 12j | +0.611pp | +0.701pp | 0.657pp | - |
| 24j | +1.714pp | +1.148pp | 1.430pp | - |
| 48j | +2.274pp | +2.020pp | 2.146pp | - |
| 72j | +3.694pp | +2.324pp | 3.006pp | - |

BH-FDR (cluster p): h4 q=0.0003, h12 q=0.0001, h24 q=0.0000, h48 q=0.0000, h72 q=0.0000

## Cara membaca

- **LOLOS** = batas bawah CI95 cluster > 0, artinya edge masih ada walau korelasi entry diperhitungkan.
- Kolom **biaya tahan** = berapa pp biaya tambahan (slippage/impact) yang masih bisa diserap sebelum edge habis. Ini bantalan realistis, bukan bonus.
- Edge yang hanya hidup di satu paruh atau satu arah = rapuh; jangan naikkan.
- Taruhan uang nyata tetap butuh bukti lane hidup (n≥20 per arm), bukan hanya replay.
