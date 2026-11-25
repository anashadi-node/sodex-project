# PRAREG-17 — FORWARD-ONLY rangepos kuintil pada SoDEX 1h — dibekukan 2026-10-09

Protokol beku (berkas otoritatif untuk harness): `reports/sodex/PRAREG17_FORWARD_RANGEPOS_PROTOCOL.json`
Harness: `scripts/research/rangepos_forward_eval.py` → `reports/sodex/RANGEPOS_FORWARD_EVAL.json`
Timer: `systemd/sodex-rangepos-forward.{service,timer}` (6 jam, read-only, tanpa order)

## AMANDEMEN-1 (2026-10-09) — arah dibalik ke REVERSAL
Versi 1 prareg ini membekukan arah **momentum** (+`range_sig`) — **itu salah arah**. Bukti:
- PRAREG-4 (SoDEX 1h, rank-proporsional): arah momentum bruto **negatif di seluruh grid** (−1,93 … −16,93 bps); arah **reversal** positif **+10,58 bps net @48 jam, t=4,35**, lolos uji **null 10-seed** (z=+2,28).
- Pengukuran kuintil kami (D1, `reports/sodex/RANGEPOS_H55_DESCRIPTIVE.json`): momentum H=48 bruto **−20,5 bps, t=−3,79** → negatif signifikan.

Maka mekanisme forward = **REVERSAL** (short yang dekat puncak rentang, long yang dekat dasar).

**Jendela forward yang terpakai: NOL.** `RANGEPOS_FORWARD_EVAL.json` mencatat `bar_forward = 0` untuk semua sel (data 1h terakhir 2026-10-08T21:00Z lebih tua dari freeze_ts versi 1). Jadi pembalikan ini **tidak membakar data** dan **tidak mengubah** satu pun gerbang/ambang/hold/biaya. `freeze_ts` baru = waktu commit amandemen ini.
**Dicatat terbuka:** arah dipilih dari lead historis (seleksi post-hoc) — karena itu verdict tetap hanya sah dari bar > freeze_ts baru.

## AMANDEMEN-2 (2026-10-09) — dua varian dibekukan, keluarga 4 sel
Lead terkuat secara statistik adalah varian **rank-proporsional** (PRAREG-4: +10,58 bps net @48 jam, **t=4,35**, S_ann 3,06, lolos null 10-seed). Versi **kuintil** dari lead yang sama (D2, `reports/sodex/RANGEPOS_H55_REVERSAL_DESCRIPTIVE.json`) memberi **+13,14 bps net @48 jam tetapi t=1,89** — SE ≈3× lebih besar karena hanya 40% nama ekstrem yang dibobot.
Karena itu keluarga sel diperluas: **{rank, kuintil} × {48 PRIMER, 55 sekunder}** = 4 sel, **BH-FDR q=0,10** (multiplisitas dibayar, bukan disembunyikan).
Catatan teknis: di modul beku `xsec_mech_study`, arm `RANGEPOS` = `-((px−lo20)/(hi20−lo20))` → **sudah arah reversal**, jadi varian rank tidak dibalik lagi; `xs.PPY` diset **8760** untuk panel 1h (modul memperingatkan bug `365/hold`). Jendela terpakai masih **nol**.

## Kenapa ada prareg ini
Keputusan Mas Anas 2026-10-09 (jawaban memo `docs/sodex/MEMO_KEPUTUSAN_TARGET_UTAMA_2026-10-09.md`):
mode **D — kumpulkan bukti**; **R2** leverage diizinkan; **R3** horizon maksimum 55 jam; **R4** venue utama SoDEX.
Mekanisme terbaik sejauh ini adalah **rangepos kuintil** (Binance 1d: +22,74 bps/48 jam, t=3,75, 7 tahun, 245 nama, lolos BH-FDR).
Di SoDEX tanda sama tetapi belum signifikan (H2 +15,73 bps; H1 +13,38 bps dengan kontrol bocor; t ≤ 1,46) — dan window SoDEX sudah terpakai (PRAREG-2/3/4).
Maka satu-satunya sumber verdict yang sah adalah **data forward**.

## Definisi (beku, verbatim PRAREG-3)
- Mekanisme: `range_sig(px, 20)` + `quantile_w(q=5)` — long kuintil teratas, short kuintil terbawah, dollar-neutral, SUM|w| = 1. Modul beku diimpor **apa adanya**, tidak ada definisi ulang.
- Hold: **48 jam (PRIMER)**, 55 jam (sekunder, sesuai R3).
- Biaya primer: **9,71 bps round-trip** (taker 4 bps/sisi × 9,71/8,0); 1× dan 2× dilaporkan sebagai stress.
- Leverage: **1×** — leverage >1× DILARANG di prareg ini sampai pagar amandemen §4 disetujui.
- Jendela: bar 1h dengan timestamp **> freeze_ts** (= waktu commit berkas protokol).
- Annualisasi: PPY = 365×24 (koreksi eksplisit 5,8962× atas konvensi harian modul beku).
- Kontrol negatif: shuffle-dalam-baris; gross kontrol harus **lebih kecil** dari gross nyata.

## Gerbang (identik PRAREG-16, tidak dilonggarkan)
gross > 0 · net > 0 · turnover ≤ 1,5 · |t_ctrl| < 2,0 · t ≥ 1,96 · S_ann ≥ 2,3 · S_fee2x ≥ 1,8 · seg+ ≥ 3 (bila n ≥ 90) · n_min_verdict 40 · n_stop_futility 20.
Keluarga venue primer = 2 sel (48 primer, 55 sekunder) → **BH-FDR q=0,10**. Hold 55 tidak boleh menggantikan 48 sebagai dasar verdict target 0,8%/48 jam.

## Batas realistis (dinyatakan terbuka)
Hold 48 jam ⇒ ~**21 jendela non-overlap** sampai HARD_STOP 20 Nov 2026 (42 hari) ⇒ ambang n ≥ 40 **kemungkinan besar tidak tercapai**. Karena itu PRAREG-17 adalah **instrumentasi forward**, bukan janji verdict.

## Yang tidak diubah
Target 0,8%/48 jam · HARD_STOP 20 Nov 2026 · semua ambang prareg lain · lane uang tetap freeze (unfreeze = execution arbiter + persetujuan) · tanpa order, tanpa perubahan live flag.
