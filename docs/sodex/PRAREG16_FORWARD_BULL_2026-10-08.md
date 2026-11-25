# PRAREG-16 — Forward-Only: MACD_FADE_H48 Rezim BULL di SoDEX

**Tanggal:** 2026-10-08 · **Status:** TERBEKU — di-commit SEBELUM jendela forward mana pun dievaluasi.
**Otoritas:** Keputusan Mas Anas 2026-10-08 (Opsi B pasca-TA15). Target 0,8%/48 jam **tidak berubah**. HARD_STOP 20 Nov 2026.

## Latar

TA15 (PRAREG-15) = 0/18 lolos. Satu sel tersisa dengan statistik menarik:

`MACD_FADE_H48|BULL|sodex` — n=49, net **+39,97 bps**, t=9,61, |t_ctrl|=0,95, S_ann=4,59, S_fee2x=4,00 → lolos **semua** gerbang kecuali **seg (struktural: n<90 = plafon umur venue 2025-10-12)**. Binance BULL berlawanan tanda (IC −0,0149) → R1 lintas-venue gagal; belum terkonfirmasi.

Karena sel ini dipilih **post-hoc** dari 18 sel TA15 + riwayat, verdict hanya sah dari **data forward**.

## Hipotesis tunggal

Pada bar 1h SoDEX **setelah freeze**, portfolio fade `MACD_HIST` (hold 48 jam) yang dibatasi ke rezim BULL menghasilkan net > 0 setelah fee, |t_ctrl| < 2,0, S_ann ≥ 2,3.

## Definisi dibekukan

| Aspek | Nilai |
|---|---|
| Sinyal | `MACD_FADE = −MACD_HIST` via `ta7.build_ta_signals` (identik TA15 ARM_MAP) |
| Hold | 48 jam |
| Venue primer | sodex (binance hanya cek tanda IC, bukan verdict) |
| Rezim | BULL = close₁D > EMA10 > EMA30 (span 10/30, adjust=False), shift(1); kolom BTC venue sendiri (FIX PRAREG-15) |
| Masking | bar non-BULL → NaN (run_mech skip) |
| Biaya | SoDEX taker 4 bps/sisi; S_fee2x pakai fee_mult=2,0 |
| Mesin | `xs.run_mech` beku (MIN_NAMES=20, SEG_MIN=30, seed kontrol 20261007); PPY=365×24 |

**Jendela forward:** bar 1h dengan timestamp > `freeze_ts` (= waktu commit berkas ini, dibaca dari `git log`); grid anchor di bar pertama sesudah freeze (konvensi identik PRAREG-12/`ta12_forward_eval.py`). Hasil dihitung ulang penuh dari data tersimpan (idempotent, tanpa state tersembunyi).

## Gerbang — identik, tidak dilonggarkan

gross>0 · net>0 · to≤1,5 · |t_ctrl|<2,0 · t≥1,96 · S_ann≥2,3 · S_fee2x≥1,8 · seg≥3 (bila n≥90) · n_min_verdict=40 · n_stop_futility=20.
**BH FDR tidak dipakai** (hipotesis tunggal prareg, bukan keluarga).

## Tier verdict (dideklarasikan)

| Kondisi | Tier |
|---|---|
| n < 20 | TIDAK_KONKLUSIF |
| n≥20 & net≤0 & t≤−1,5 | FALSIFIED (stop_futility) |
| n≥40 & semua gerbang termasuk seg | LULUS_MESIN (kandidat sertifikasi) |
| n≥40 & semua gerbang KECUALI seg (n<90 struktural) | PROMISING_UNCERTIFIED (bukan verdict mesin) |
| lainnya | FALSIFIED (daftar gerbang) |

## Batas realistis (dideklarasikan terbuka)

Rezim BULL ~27–37% hari → jendela 48 jam yang masuk BULL ≈ **1 per 6–8 hari**. Sampai HARD_STOP (43 hari) ekspektasi **n ≈ 5–8** → ambang n≥40 kemungkinan besar **tidak tercapai** dalam horizon ini. PRAREG-16 adalah instrumentasi forward yang sah, bukan janji verdict.

## Tidak diubah

Semua gerbang/ambang/definisi · tidak ada order, tidak ada perubahan live flag, read-only murni · target 0,8%/48 jam & HARD_STOP tetap.

**Keluaran:** `reports/sodex/TA16_FORWARD_BULL.json` (timer harian) + `logs/sodex_ta16_forward.log`.
