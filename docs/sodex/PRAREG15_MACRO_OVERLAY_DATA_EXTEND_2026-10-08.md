# PRAREG-15 — Perpanjangan DATA Panel Binance + Koreksi Sumber Rezim BTC (Opsi A pasca-TA14)

**Tanggal prareg (UTC):** 2026-10-08 · **Status:** TERBEKU — di-commit SEBELUM backfill & evaluasi.
**Otoritas:** Keputusan Mas Anas 2026-10-08 (Opsi A): **tambah DATA, bukan melonggarkan gerbang.** Target 0,8%/48 jam tidak berubah. HARD_STOP 20 Nov 2026.

## Latar

- PRAREG-13 (rezim lambat EMA50/200): **0/18**. PRAREG-14 (rezim cepat EMA10/30): **0/18**.
- Near-miss terkuat lintas-prareg `MACD_FADE_H48|BEAR|binance` gagal **hanya** kanal segmen yang struktural: panel 402 hari → n maksimum 77 < 90 (= 3×SEG_MIN) → segmen tak pernah terhitung pada definisi rezim cepat.

## Dua perubahan yang dideklarasikan SEBELUM hasil

1. **Tambah DATA (inti Opsi A).** Panel Binance 1h diperpanjang ke belakang: mulai **2024-01-01T00:00Z** (sebelumnya 2025-09-01) + refresh ekor. Skrip baru `scripts/research/binance_backfill_klines_1h.py` (merge dedup, schema tak berubah, resumable). Puller beku **tidak disentuh**; komposisi universe **tidak diubah** (54 simbol); `data/` gitignored.
2. **Koreksi bug sumber rezim — dideklarasikan terbuka.** Pemilih kolom rezim TA13/TA14 (`"BTCUSDT" else px.columns[0]`) diam-diam memakai **1000BONK-USD** di venue SoDEX (kolom panel `{SYM}-USD`; `BTCUSDT` tak pernah cocok; fallback urut abjad = BONK; `BTC-USD` ada tapi tak dicocokkan). Bukti murni hitungan bar (tanpa sinyal/PnL): distribusi rezim SoDEX TA14 = 1.272/1.427/3.432 bar = persis rezim BONK 257 hari; BTC-USD = 98/116/147 hari dari 362 hari. Jadi sel SoDEX TA13/TA14 sesungguhnya overlay rezim **BONK**. **FIX:** kolom rezim = `BTCUSDT` bila ada, elif `BTC-USD`, else fallback — kedua venue memakai seri BTC venue-nya sendiri, sesuai maksud teks prareg-13/14. Hasil TA13/TA14 tetap sah sebagai historis-deskriptif (0/18; tak ada keputusan yang dibuat darinya).

## Yang TIDAK diubah

ARM_MAP (3 arm, hold 48) · 18 sel · **N_MIN=40** · gerbang penuh identik panel beku TA10 (gross>0; net>0; to≤1,5; |t_ctrl|<2,0; t≥1,96; S_ann≥2,3; S_fee2x≥1,8; seg 3/3; BH q≤0,10; n≥40) · BH keluarga q=0,10 · mesin beku `run_mech` (seed 20261007), SEG_MIN=30 · fee, turnover, kontrol shuffle · no-lookahead shift(1) · tanpa trim warmup EMA.

## Ekspektasi n (power analysis murni — hitung bar saja)

| Venue | Hari | BULL/CHOP/BEAR (hari) | est. n window | Kanal segmen (n≥90) |
|---|---|---|---|---|
| SoDEX (BTC-USD, 362 h) | 362 | 98/116/147 | 49/58/73 | tetap n/a struktural (umur venue) |
| Binance sebelum | 402 | bar 3000/3024/3600 | 62/63/75 | n/a (n<90) |
| Binance sesudah backfill | ~1.011 | — | ~150–190 | **terhitung** |

Angka aktual pasca-backfill dihitung dari hitungan bar saja dan dilaporkan di hasil.

## Konsekuensi jujur

Kanal segmen hanya mungkin tercapai di sel **Binance**; sel SoDEX tetap gagal seg struktural (umur venue). Kandidat lolos penuh realistis hanya mungkin di sel binance. R1 lintas-venue tetap syarat tambahan.

## Kriteria keputusan

0 lolos → keluarga fade H48 (4 prareg, 70 sel) ditutup / diputuskan Mas Anas. ≥1 lolos → **kandidat forward** (PRAREG-16), bukan verdict mesin. Hasil historis selalu DESKRIPTIF.
