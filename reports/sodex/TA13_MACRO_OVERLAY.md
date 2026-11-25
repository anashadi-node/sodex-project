# TA13 — Hasil Uji Overlay Makro Rezim BTC pada Kandidat Fade H48

Prareg: `reports/sodex/PRAREG13_MACRO_OVERLAY_PROTOCOL.json` (TERBEKU, commit `b9fb8b3`, ditulis SEBELUM evaluasi)
Skrip: `scripts/research/ta13_macro_overlay.py` · Mesin: `xsec_mech_study.run_mech` (beku, tidak diubah)
Sifat hasil: **HISTORIS-DESKRIPTIF** — tidak ada verdict mesin dari data historis.

## 1. Sebaran rezim (definisi beku: EMA50/EMA200 pada BTC 1D)

| Venue | BULL (bar) | CHOP (bar) | BEAR (bar) | Total bar panel |
|---|---|---|---|---|
| SoDEX | 72 | 1.565 | 4.488 | 8.550 |
| Binance | 1.488 | 2.952 | 5.184 | 9.648 |

Catatan keterbatasan: **rezim BULL praktis tidak teruji di SoDEX** (72 bar = 3 hari => 1 window).
Panel SoDEX didominasi BEAR (52% bar) dan CHOP (18%). Karena definisi rezim dibekukan di prareg,
ini dilaporkan apa adanya, bukan "diperbaiki" setelah melihat hasil.

## 2. Hasil 18 sel (3 arm x 3 rezim x 2 venue)

| Sel | n | net bps | to | t | \|t_ctrl\| | S_ann | S_fee2x | seg | BH | Gerbang |
|---|---|---|---|---|---|---|---|---|---|---|
| MACD_FADE_H48\|BEAR\|binance | 110 | 20,42 | 1,32 | 4,95 | 0,09 | 2,46 | 1,66 | 3/3 | Y | **gagal hanya S_fee2x<1,8** |
| MACD_FADE_H48\|BEAR\|sodex | 93 | 16,62 | 1,33 | 1,22 | 0,32 | 1,80 | 1,23 | 2/3 | F | t<1,96 |
| MACD_FADE_H48\|BULL\|binance | 31 | 25,42 | 1,30 | 2,12 | 0,12 | 2,16 | 1,61 | - | F | n<40 MONITOR |
| MACD_FADE_H48\|BULL\|sodex | 1 | (109,40) | 1,00 | - | - | - | - | - | F | n<40 MONITOR |
| MACD_FADE_H48\|CHOP\|binance | 58 | 0,89 | 1,31 | 0,12 | 2,43 | 0,09 | -0,55 | - | F | t<1,96 |
| MACD_FADE_H48\|CHOP\|sodex | 33 | 37,42 | 1,27 | 8,54 | **4,27** | 4,84 | 4,19 | - | Y | n<40 + **\|t_ctrl\| artefak** |
| KONFL_FADE_H48\|BEAR\|binance | 110 | 4,10 | 1,35 | 1,64 | 1,80 | 0,62 | -0,40 | 3/3 | F | t<1,96 |
| KONFL_FADE_H48\|BEAR\|sodex | 93 | 6,21 | 1,36 | 0,86 | 0,72 | 0,86 | 0,10 | 2/3 | F | t<1,96 |
| KONFL_FADE_H48\|BULL\|binance | 31 | 12,42 | 1,31 | 1,66 | 1,27 | 1,42 | 0,67 | - | F | n<40 MONITOR |
| KONFL_FADE_H48\|BULL\|sodex | 1 | (186,59) | 1,00 | - | - | - | - | - | F | n<40 MONITOR |
| KONFL_FADE_H48\|CHOP\|binance | 58 | -35,40 | 1,35 | -4,51 | 1,21 | -3,87 | -4,60 | - | Y | net<0 |
| KONFL_FADE_H48\|CHOP\|sodex | 33 | 9,52 | 1,37 | 1,63 | 2,63 | 1,15 | 0,49 | - | F | n<40 |
| BB_POS_H48\|BEAR\|binance | 110 | 4,96 | 1,28 | 0,81 | 1,43 | 0,65 | -0,19 | 1/3 | F | t<1,96 |
| BB_POS_H48\|BEAR\|sodex | 93 | 1,49 | 1,30 | 0,19 | 0,08 | 0,20 | -0,50 | 1/3 | F | t<1,96 |
| BB_POS_H48\|BULL\|binance | 31 | -16,49 | 1,26 | -1,30 | 0,95 | -1,40 | -1,94 | - | F | net<0 |
| BB_POS_H48\|BULL\|sodex | 1 | (199,96) | 1,00 | - | - | - | - | - | F | n<40 MONITOR |
| BB_POS_H48\|CHOP\|binance | 58 | -5,00 | 1,32 | -0,48 | 3,81 | -0,57 | -1,33 | - | F | net<0 |
| BB_POS_H48\|CHOP\|sodex | 33 | 16,47 | 1,29 | 3,06 | 0,35 | 2,95 | 2,03 | - | Y | n<40 MONITOR |

## 3. Verdict

**0 dari 18 sel lolos gerbang penuh.** Hipotesis "edge H48 bersifat kondisional pada rezim makro BTC
(definisi EMA50/EMA200 1D)" **tidak terkonfirmasi** pada panel ini.

Temuan penting (deskriptif, bukan klaim edge):

1. **Near-miss terkuat sejauh ini**: `MACD_FADE_H48|BEAR|binance` — n=110, net 20,42 bps, t=4,95,
   `|t_ctrl|`=0,09 (spesifisitas kontrol sangat baik), segmen 3/3, BH lulus; **gagal hanya di
   S_fee2x = 1,66 < 1,80**. Gerbang tidak dilonggarkan; karenanya sel ini TIDAK dipromosikan ke forward.
2. **Asimetri venue**: pada rezim BEAR yang sama, Binance t=4,95 sementara SoDEX t=1,22.
3. **Pelajaran artefak kontrol**: `MACD_FADE_H48|CHOP|sodex` menunjukkan t=8,54 dan S_ann=4,84 —
   tetapi `|t_ctrl|`=4,27, artinya arah-acak di mesin yang sama menghasilkan keunggulan serupa.
   Ini contoh persis mengapa gerbang `|t_ctrl|`<2,0 menyelamatkan sistem dari kesimpulan palsu.
4. **BULL tidak teruji di SoDEX** (72 bar panel); di Binance pun hanya 31 window (<40 => MONITOR).

## 4. R1 lintas-venue

8 dari 9 sel yang sebanding lolos R1 (tanda IC sama dan |IC_sodex| >= 0,5|IC_binance|). Satu sel gagal
(kombinasi BB_POS pada rezim tertentu). R1 lulus tidak cukup untuk lulus mesin — sel tetap harus lulus
seluruh gerbang pada kedua venue.

## 5. Deklarasi terbuka

Selama pengerjaan, ditemukan bug pada skrip baru (`DataFrame.where` dengan array mask berbentuk salah)
lalu diperbaiki menjadi `.mask(~series, axis=0)`. Perbaikan dinyatakan terbuka; **tidak** ada perubahan
pada prareg, mesin beku, ambang, atau data.

## 6. Kesimpulan & langkah berikut

- Definisi rezim lambat (EMA50/EMA200) tidak membuka sel mana pun, dan meninggalkan rezim BULL tanpa sampel.
- Jalan berikutnya yang patuh protokol: **PRAREG-14 baru** (dideklarasikan sebelum evaluasi) dengan definisi
  rezim lebih cepat (mis. EMA10/EMA30 1D, atau state dari slope EMA50) sehingga ketiga rezim punya sampel
  cukup; ATAU mengakui bahwa keluarga fade H48 sudah dua kali gagal dan menghentikan jalur ini.
- Tidak ada parameter, target, atau gerbang yang diubah oleh dokumen ini.
