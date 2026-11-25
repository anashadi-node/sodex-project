# PRAREG-34 — Studi leverage (perp) untuk Mode A/B2

Rencana dibekukan 26-Okt-2026 SEBELUM hasil (hash + 2 amandemen di `reports/sodex/PRAREG34_REGISTRY.jsonl`). RISET read-only: tanpa order, tanpa kredensial, tanpa mengubah parameter engine/live.

## Pertanyaan
Apakah leverage L>1 lewat perp membuat arm A atau B2 mencapai **M ≥ 0,010 %/5 jam netto** (biaya 10 bps + funding) **tanpa** melanggar plafon risiko, dan apakah edge-nya **terbukti** (bukan hanya lebih besar)?

## Gerbang (beku)
A: M_2022+ ≥ 0,010 · B: M_2024+ > 0 dan M_OOS26 > 0 · C: 0 hari likuidasi stres (gerak merugikan ×1,5 dari low harian) dan MDD_2022+ ≥ −35% · D: bootstrap blok p(M≤0) < 0,05 **dan** kontrol geser-waktu p < 0,05.
Vonis: `TIDAK_LAYAK` (A/B/C gagal) · `LAYAK_PAPER_BUKAN_BUKTI` (A,B,C lulus, D gagal) · `TERBUKTI`.

## Hasil (data: ETF/spot 2019→, main 2022-01→2026-10-25; funding Binance USDM 8 jam)
| Arm | L | M 2022+ | M 2024+ | M OOS26 | MDD | win31 terburuk | likuidasi stres | ekuitas stres min | p(M≤0) | p kontrol | vonis |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A spot | 1 | **0,00606** | — | — | −13,8 | — | — | — | 0,10 | 0,10 | acuan |
| A perp | 1 | 0,00418 | 0,00623 | 0,00136 | −14,2 | −9,6% | 0 | 0,758 | 0,110 | 0,166 | TIDAK_LAYAK |
| A perp | 1,5 | 0,00629 | 0,00931 | 0,00214 | −20,5 | −13,8% | 0 | 0,656 | 0,106 | — | TIDAK_LAYAK |
| A perp | 2 | 0,00884 | 0,01328 | 0,00254 | −26,5 | −18,5% | 0 | 0,586 | 0,101 | 0,133 | TIDAK_LAYAK |
| A perp | 3 | 0,01295 | 0,01913 | 0,00430 | **−39,3** | −29,6% | 0 | 0,392 | 0,106 | — | TIDAK_LAYAK (MDD) |
| B2 spot | 1 | **0,00906** | — | — | −19,5 | — | — | — | 0,05 | — | acuan |
| B2 perp | 1 | 0,00657 | 0,01057 | 0,00095 | −19,5 | −9,7% | 0 | 0,758 | 0,052 | 0,070 | TIDAK_LAYAK |
| B2 perp | 1,5 | 0,00991 | 0,01604 | 0,00154 | −27,0 | −14,5% | 0 | 0,656 | 0,049 | — | TIDAK_LAYAK |
| B2 perp | 2 | **0,01382** | 0,02227 | 0,00220 | −33,9 | −18,8% | 0 | 0,586 | 0,042 | 0,060 | **LAYAK_PAPER_BUKAN_BUKTI** |
| B2 perp | 3 | 0,02029 | 0,03262 | 0,00388 | **−46,6** | −26,6% | 0 | 0,392 | 0,046 | — | TIDAK_LAYAK (MDD) |

Titik kritis (grid 0,5): L pertama M≥target: A 3,0 / B2 2,0 · L pertama MDD < −35%: **2,5 (keduanya)** · L pertama likuidasi stres: **4,5** · likuidasi tanpa stres: 6,5 · puncak pertumbuhan geometrik (Kelly): 4,5 (di luar batas likuidasi → tidak boleh dipakai).

## Temuan
1. **Leverage tidak menambah bukti.** p(M≤0) praktis datar: A 0,110→0,101; B2 0,052→0,042 sepanjang L=1→3. Ini memang identitas matematis (t-stat invarian terhadap skala). Yang berubah hanya besar taruhannya.
2. **Perp 1× lebih buruk daripada spot**: A 0,00418 vs 0,00606 (−31%); B2 0,00657 vs 0,00906 (−27%). Funding 1,79 bps/hari (BTC 2022+) > penghematan fee (spot 6,5 vs perp 4 bps taker).
3. **Hanya B2 pada L=2** yang memenuhi target **dan** plafon risiko. Tapi MDD −33,9% (nyaris menyentuh plafon), jendela 31-hari terburuk −18,8%, P(win31 ≥ target) = 0,439, dan kontrol acak p = 0,060 → **bukan bukti**.
4. **Multiplisitas:** 8 sel diuji; dengan BH 5% ambang p terkecil = 0,00625. Tidak ada sel yang lolos. Vonis tidak berubah, tapi klaim signifikansi mentah (0,042) tidak boleh dipakai.
5. Triangulasi funding: SoDEX BTC 24 hari 1,23 bps/hari vs Binance jendela sama 1,00 → memakai Binance 2022+ (1,79) **konservatif**.
6. Likuidasi historis (2022+) belum terpicu di L≤3, dengan jarak ekuitas stres 0,586 pada L=2. Itu bukan jaminan: sampel tidak memuat gap >40% pada BTC/ETH sejak 2022.

## Kesimpulan
Perp/leverage **boleh dipakai secara teknis** (bukan Red Line selama dry-run + GO-LIVE terpisah), tetapi secara terukur ia **bukan** jalan menuju target 0,010 tanpa membayar risiko: titik di mana target tercapai (L≈2–3) hampir bersamaan dengan titik MDD menembus plafon (L=2,5). Untuk A tidak ada konfigurasi yang layak. Untuk B2 hanya L=2, berstatus **layak diuji paper, bukan terbukti**.

## Hipotesis lanjutan (BELUM diuji — butuh PRAREG baru)
**Hybrid spot+perp:** tahan 1× di spot (tanpa funding), lapisan di atas 1× lewat perp. Secara aritmetika drag funding hanya kena porsi (L−1) sehingga B2 L=2 diperkirakan ≈ 0,015 (bukan 0,0138), dengan MDD hampir sama. Belum dijalankan; angka ini **bukan hasil**, hanya perkiraan yang harus diuji sendiri.

## Asumsi yang perlu persetujuan pengguna
Plafon MDD −35% adalah asumsi peneliti, bukan preferensi Anda. Semua eksposur dimodelkan via perp sehingga funding dibayar pada seluruh notional.
