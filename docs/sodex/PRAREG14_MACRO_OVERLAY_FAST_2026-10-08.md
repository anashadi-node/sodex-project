# PRAREG-14 — Overlay Rezim BTC Definisi Cepat (EMA10/EMA30 1D) pada Kandidat Fade H48

Status: **TERBEKU** — ditulis dan di-commit SEBELUM evaluasi dijalankan.
Tanggal prareg: 2026-10-08 · Lingkup: SoDEX (proyek SODEX) · Pilar: 4 (ekosistem reaktif-antisipatif)
Versi mesin: `reports/sodex/PRAREG14_MACRO_OVERLAY_FAST_PROTOCOL.json`

## 1. Latar belakang & keputusan

PRAREG-13 (rezim lambat EMA50/EMA200, commit `b9fb8b3`): **0/18 sel lolos**; rezim BULL praktis
tidak teruji di SoDEX (72 bar ≈ 1 window). Keputusan Mas Anas (**Opsi A**): uji ulang hipotesis
rezim-kondisional dengan **definisi rezim lebih cepat** agar ketiga rezim memperoleh sampel.
Gerbang, mesin, arm, hold, fee, kontrol — semuanya identik; **hanya definisi rezim yang berubah**.

## 2. Seleksi definisi (dideklarasikan terbuka, sebelum hasil)

Pemilihan dilakukan lewat **power analysis murni** — hitungan distribusi bar rezim pada panel beku,
TANPA melihat sinyal/PnL. Empat kandidat diprobe:

| Kandidat | SoDEX hari BULL/CHOP/BEAR | transisi | Est. n window SoDEX (B/C/Be) |
|---|---|---|---|
| **EMA10/30** | 53/60/143 | 49 | **26/30/71** |
| EMA20/50 | 35/67/154 | 37 | 17/33/77 |
| EMA5/20 | 58/76/122 | 84 | 29/38/61 |
| SLOPE_EMA20_L5 | 73/30/153 | 40 | 36/15/76 |

**Dibekukan: EMA10/EMA30** — paling seimbang. Konsekuensi yang DITERIMA sebelum hasil: sel SoDEX
BULL & CHOP diperkirakan **n<40 → MONITOR** (panel SoDEX hanya 257 hari ber-data). **N_MIN=40
TIDAK diturunkan** demi mengakomodasi ini — menurunkannya demi membuat sel lolos adalah pelonggaran
yang dilarang.

## 3. Definisi rezim (prareg, tidak boleh diubah setelah hasil)

- Sumber: kolom **BTCUSDT** panel beku venue, close harian (`resample('1D').last()`).
- Aturan: EMA10 & EMA30 (span 10/30, `adjust=False`).
  - **BULL** jika close > EMA10 > EMA30 · **BEAR** jika close < EMA10 < EMA30 · **CHOP** selain itu.
- Tanpa lookahead: `st.shift(1)` pada baris harian (konvensi identik TA13).
- Deterministik dari panel beku (tidak bergantung cache timer lain).

## 4. Sinyal, mesin, keluarga, gerbang

- Mesin `xsec_mech_study.run_mech` (beku), hold=48; arms MACD_FADE_H48 / KONFL_FADE_H48 / BB_POS_H48.
- Overlay: sinyal NaN di luar rezim (pola `.mask(~m, axis=0)` TA13); fee, kontrol shuffle seed
  20261007, segmen, turnover — identik TA10/TA13.
- Keluarga: 3 arm × 3 rezim × 2 venue = **18 hipotesis**, BH FDR q=0,10 pada keluarga.
- Gerbang persis panel beku: gross>0; net>0; to≤1,5; |t_ctrl|<2,0; t≥1,96; S_ann≥2,3; S_fee2x≥1,8;
  seg 3/3; corr(IC,gross)>0; R1 lintas-venue; n≥40/sel (MONITOR bila kurang).

## 5. Batas klaim

Hasil historis **DESKRIPtif**. Lulus gerbang = kandidat harness forward baru (**PRAREG-15**),
bukan verdict mesin. Verdict mesin hanya dari data forward. Tidak ada target/parameter yang berubah.

## 6. Yang tidak dilakukan

Tidak mengubah skrip beku; tidak menurunkan N_MIN; tidak mengubah target 0,8%; tidak menyentuh
berkas proyek lain; tidak menulis kredensial.
