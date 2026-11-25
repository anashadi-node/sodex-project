# PRAREG-13 — Overlay Makro Rezim BTC pada Kandidat Fade H48

Status: **TERBEKU** — ditulis dan di-commit SEBELUM evaluasi dijalankan.
Tanggal prareg: 2026-10-08 · Lingkup: SoDEX (proyek SODEX) · Pilar: 4 (ekosistem reaktif-antisipatif)
Versi mesin: `reports/sodex/PRAREG13_MACRO_OVERLAY_PROTOCOL.json`

## 1. Latar belakang

Seluruh keluarga arm H48 (TA10) dan arm geometri exit (TA11) mati di gerbang spesifisitas kontrol:
`|t_ctrl|` = 2,92-4,49 padahal ambang 2,0. Artinya keunggulan mereka tidak dapat dibedakan dari efek
arah-acak. Hipotesis berikutnya yang wajar: **edge itu bersifat kondisional pada rezim makro BTC** —
sinyal yang tampak tidak spesifik secara keseluruhan bisa jadi spesifik ketika hanya dihitung pada rezim
tertentu.

## 2. Definisi rezim (prareg, tidak boleh diubah setelah hasil)

- Sumber: kolom **BTCUSDT** pada panel beku venue (SoDEX / Binance), close harian (`resample('1D').last()`).
- Aturan: EMA50 dan EMA200 atas close harian (span 50/200, `adjust=False`).
  - **BULL** jika close > EMA50 > EMA200
  - **BEAR** jika close < EMA50 < EMA200
  - **CHOP** selain itu
- Tanpa lookahead: rezim hari D dipakai mulai bar jam pertama hari D+1.
- Alasan memakai panel beku: replikasi deterministik, tidak bergantung cache yang ditulis timer lain.

## 3. Definisi sinyal & mesin

- Mesin: `xsec_mech_study.run_mech` (**beku**, tidak diubah), `hold=48`.
- Arms: `MACD_FADE_H48` (MACD_HIST x -1), `KONFL_FADE_H48` (KONFLUENSI x -1), `BB_POS_H48` (BB_POS x +1).
- Overlay: sinyal hanya aktif pada bar yang rezimnya = R; bar lain diset NaN. `run_mech` sudah melewati
  bar dengan nama kurang dari ambang, sehingga tidak ada logika mesin baru.
- Fee, turnover, kontrol shuffle (seed 20261007), segmen, BH — identik dengan TA10.

## 4. Keluarga hipotesis & gerbang

- Keluarga uji: 3 arm x 3 rezim x 2 venue = **18 hipotesis**; BH FDR q = 0,10 pada keluarga 18.
- Gerbang (persis panel beku): gross > 0; net > 0; turnover <= 1,5; `|t_ctrl|` < 2,0; t >= 1,96;
  S_ann >= 2,3; S_fee2x >= 1,8; segmen positif 3/3; corr(IC, gross) > 0; R1 lintas-venue; **n per sel >= 40**.
- Bila n per sel < 40: status **MONITOR**, tanpa verdict.

## 5. Deklarasi risiko overfit dan batas klaim

Memilih rezim terbaik dari tiga adalah penelitian berganda. Mitigasi: seluruh rezim dilaporkan,
BH q = 0,10, kontrol arah-acak, syarat n >= 40. Tidak ada gerbang yang diturunkan. Hasil historis bersifat
**DESKRIPTIF**; lulus gerbang hanya menandai kandidat untuk harness forward baru (PRAREG-14), bukan verdict mesin.

## 6. Yang tidak dilakukan

Tidak mengubah skrip beku; tidak mengubah target 0,8% atau parameter risiko; tidak menyentuh berkas
proyek lain; tidak menulis kredensial.
