# TA14 — Hasil Uji Overlay Rezim BTC Definisi Cepat (EMA10/EMA30 1D)

Prareg: `reports/sodex/PRAREG14_MACRO_OVERLAY_FAST_PROTOCOL.json` (TERBEKU, commit `6dc60ff`, ditulis SEBELUM evaluasi)
Skrip: `scripts/research/ta14_macro_overlay_fast.py` · Mesin: `xsec_mech_study.run_mech` (beku, tidak diubah)
Sifat hasil: **HISTORIS-DESKRIPTIF** — tidak ada verdict mesin dari data historis.

## 1. Sebaran bar per rezim (definisi beku: EMA10/EMA30 pada BTC 1D)

| Venue | BULL | CHOP | BEAR | Total |
|---|---|---|---|---|
| SoDEX | 1.272 | 1.427 | 3.432 | 8.556 |
| Binance | 3.000 | 3.024 | 3.600 | 9.648 |

Dibanding PRAREG-13 (lambat), rezim kini jauh lebih seimbang di Binance (purpose Opsi A tercapai
di Binance). Di SoDEX, BULL tetap tipis (1.272 bar ≈ 25 window) karena panjang panel venue terbatas.

## 2. Hasil 18 sel

| Sel | n | net bps | to | t | \|t_ctrl\| | S_ann | S_fee2x | seg | BH | Gerbang |
|---|---|---|---|---|---|---|---|---|---|---|
| MACD_FADE_H48\|BEAR\|binance | 77 | 33,70 | 1,32 | 6,77 | 0,18 | 3,69 | 2,96 | n/a | Y | **gagal hanya seg+** |
| MACD_FADE_H48\|BEAR\|sodex | 68 | 18,16 | 1,32 | 1,13 | 2,75 | 1,92 | 1,36 | n/a | F | \|t_ctrl\|≥2; t<1,96 |
| MACD_FADE_H48\|BULL\|binance | 60 | 25,41 | 1,30 | 2,71 | 2,49 | 2,49 | 1,85 | n/a | Y | \|t_ctrl\|≥2; seg+ |
| MACD_FADE_H48\|BULL\|sodex | 25 | 55,78 | 1,26 | 10,70 | 0,64 | 7,22 | 6,56 | n/a | Y | **MONITOR (n<40)**; seg+ |
| MACD_FADE_H48\|CHOP\|binance | 62 | -16,55 | 1,30 | -1,92 | 1,39 | -1,86 | -2,59 | n/a | Y | net≤0 |
| MACD_FADE_H48\|CHOP\|sodex | 34 | 7,74 | 1,30 | 1,46 | 2,05 | 0,94 | 0,31 | n/a | F | \|t_ctrl\|≥2; t<1,96 |
| KONFL_FADE_H48\|BEAR\|binance | 77 | 10,71 | 1,33 | 2,31 | 0,92 | 1,58 | 0,60 | n/a | Y | S_ann<2,3; S_fee2x<1,8 |
| KONFL_FADE_H48\|BEAR\|sodex | 68 | 13,95 | 1,38 | 2,06 | 2,48 | 1,86 | 1,13 | n/a | Y | \|t_ctrl\|≥2; S<2,3 |
| KONFL_FADE_H48\|BULL\|binance | 60 | -7,07 | 1,36 | -0,68 | 0,09 | -0,82 | -1,60 | n/a | F | net≤0 |
| KONFL_FADE_H48\|BULL\|sodex | 25 | 24,68 | 1,33 | 6,00 | **5,70** | 3,04 | 2,38 | n/a | Y | **artefak kontrol**; seg+ |
| KONFL_FADE_H48\|CHOP\|binance | 62 | -26,11 | 1,33 | -3,03 | 1,19 | -3,20 | -4,01 | n/a | Y | net≤0 |
| KONFL_FADE_H48\|CHOP\|sodex | 34 | -14,43 | 1,37 | -1,11 | **4,84** | -2,03 | -2,80 | n/a | F | net≤0; artefak kontrol |
| BB_POS_H48\|BEAR\|binance | 77 | 22,98 | 1,28 | 2,86 | 0,58 | 2,73 | 1,97 | n/a | Y | seg+ |
| BB_POS_H48\|BEAR\|sodex | 68 | 11,12 | 1,30 | 1,63 | 0,89 | 1,52 | 0,81 | n/a | F | t<1,96; S<2,3 |
| BB_POS_H48\|BULL\|binance | 60 | 2,22 | 1,29 | 0,24 | 0,58 | 0,25 | -0,47 | n/a | F | t<1,96 |
| BB_POS_H48\|BULL\|sodex | 25 | 31,50 | 1,31 | 9,19 | **6,89** | 5,57 | 4,64 | n/a | Y | **artefak kontrol**; MONITOR |
| BB_POS_H48\|CHOP\|binance | 62 | -34,67 | 1,28 | -3,99 | 0,92 | -4,14 | -4,90 | n/a | Y | net≤0 |
| BB_POS_H48\|CHOP\|sodex | 34 | -19,64 | 1,31 | -2,53 | 1,22 | -2,78 | -3,53 | n/a | Y | net≤0 |

`seg` = `n/a` karena keterbatasan mesin: mesin hanya membentuk 3 segmen waktu bila
`n ≥ 3×SEG_MIN = 90` (`SEG_MIN=30`); **sel terbesar TA14 hanya n=77**, sehingga kanal segmen
tak terhitung untuk SEMUA sel.

## 3. Verdict

**0 dari 18 sel lolos gerbang penuh.** R1 lintas-venue **8/9** (gagal: BB_POS\|CHOP — tanda IC
SoDEX +0,0054 vs Binance −0,0030, keduanya nyaris nol).

Temuan struktural penting (jujur, bukan pembenaran):

1. **Kanal segmen tidak dapat dicapai oleh definisi rezim cepat.** Karena window 48 jam
   non-overlap, `n ≈ bar_rezim/48`; syarat segmen butuh `n≥90 ⟺ ≥4.320 bar in-rezim`. Definisi
   cepat memecah rezim menjadi blok-blok pendek, jadi rezim mana pun di kedua panel < 90.
   Konsekuensi: untuk keluarga ber-gate-rezim, "segment 3/3" hanya mungkin lewat definisi lambat
   (blok panjang) — dan definisi lambat justru menutup jalur itu via S_fee2x (lihat §4).
2. **Near-miss terkuat lintas dua prareg: `MACD_FADE_H48|BEAR|binance`.**
   - PRAREG-13 (lambat): n=110, net 20,42, t=4,95, \|t_ctrl\|=0,09, S_fee2x=**1,66** (<1,80), seg 3/3 → gagal S_fee2x.
   - PRAREG-14 (cepat): n=77, net **33,70**, t=**6,77**, \|t_ctrl\|=**0,18**, S_ann=3,69, S_fee2x=**2,96**, BH lulus → gagal seg (n<90, tak terhitung).
   Sel ekonomi yang sama positif kuat di dua definisi berbeda, gagal di gerbang yang berbeda.
   **Tidak ada gerbang yang dilonggarkan**; statusnya tetap bukan kandidat.
3. **SoDEX BULL tetap tidak teruji** (n=25 < 40, MONITOR) — dikonfirmasi tepat seperti prediksi
   probe prareg. Ini plafon umur venue, bukan masalah definisi.
4. **Gerbang kontrol kembali menyelamatkan sistem**: `MACD_FADE_H48|BULL|sodex` (t=10,70) dan
   `KONFL_FADE_H48|BULL|sodex` (t=6,00, \|t_ctrl\|=5,70) serta `BB_POS_H48|BULL|sodex`
   (t=9,19, \|t_ctrl\|=6,89) tampak spektakuler, tetapi kontrol arah-acak menghasilkan keunggulan
   setara → tidak spesifik sinyal.

## 4. Akuntansi uji lintas-prareg (dinyatakan terbuka)

Keluarga fade H48 kini sudah diuji 3 kali: TA10 unconditional (0/16), PRAREG-13 rezim lambat
(0/18), PRAREG-14 rezim cepat (0/18) = **52 sel uji**. Koreksi BH hanya berlaku **di dalam** tiap
prareg, tidak antar-prareg. Ini keterbatasan yang dinyatakan terbuka; setiap uji baru menaikkan
peluang positif semu. Karena itu setiap prareg berikutnya hanya sah bila (i) menambah **data**
(bukan menambah derajat kebebasan definisi), atau (ii) memperketat gerbang.

## 5. Deklarasi

Tidak ada perubahan pada: target 0,8%, parameter risiko, gerbang, mesin beku, skrip beku, atau
berkas proyek lain. Definisi rezim EMA10/30 dipilih lewat power analysis pra-hasil (terdokumentasi
di prareg) dan sudah di-commit (`6dc60ff`) sebelum evaluasi dijalankan.

## 6. Langkah berikut (keputusan Mas Anas)

- **(a) PRAREG-15 — tambah DATA, bukan longgarkan gerbang**: perpanjang panel Binance 1h
  (`xs._binance_panel("1h")`, panel beku 402 hari kini) menjadi mis. 24 bulan, sehingga `n` per
  rezim dapat melewati 90 dan kanal segmen menjadi terhitung. Gerbang & keluarga 18 sel tetap
  identik. Ini satu-satunya jalur yang memberi uji adil pada kandidat terkuat tanpa melonggarkan apa pun.
- **(b) Tutup keluarga fade H48** (52 sel, tiga skema, tidak lolos) dan alihkan sumber daya ke
  geometri sinyal lain atau ke mesin portofolio pilar 4 yang sudah ada.
- **(c) Opsi lain** sesuai arahan.
