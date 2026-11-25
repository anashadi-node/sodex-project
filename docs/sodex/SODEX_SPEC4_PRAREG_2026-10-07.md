# SODEX SPEC4 — PRA-REGISTRASI (BEKU) — 2026-10-07

**Status: BEKU. Tidak ada satu pun hasil dihitung sebelum dokumen ini di-commit.**
Amendemen apa pun setelah commit ini hanya boleh **MEMPERKETAT**, tidak pernah melonggarkan.
Deviasi yang melonggarkan = hasil otomatis BATAL.

Alasan putaran ini: ALT3 (cross-sectional) **gugur** — lihat
`docs/sodex/SODEX_ALT3_HASIL_2026-10-07.md`. Diagnosis: arsitektur cross-sectional
mengasumsikan pasar DEEP & BROAD; SoDEX adalah venue **tipis** (3 nama likuid,
median pasar $328/jam). Maka kelas arsitektur dipindah — bukan strategi dipelintir.

---

## 0. Deklarasi keterbukaan (jujur, wajib dibaca)

Putaran ini adalah hipotesis ke-4+ pada data SoDEX. Jendela waktu tape
**tumpang-tindih** dengan studi H5 sebelumnya. Yang **baru**: (a) resolusi **menit**,
(b) **fitur mikro-struktur** (arus order, bukan harga), (c) kelas arsitektur
lintas-venue. Untuk menahan risiko p-hacking:
- hanya **2 hipotesis** (bukan 8 seperti ALT3),
- **OOS terkunci** (2026-09-01 → 2026-10-07) tidak disentuh sampai keputusan IS dibekukan,
- biaya **stress** 16 bp round-trip tetap wajib lolos,
- kontrol negatif wajib **gagal**.

## 1. Data

| Sumber | Cakupan | Catatan |
|---|---|---|
| SoDEX tape menit `scratch/sodex_minutes/` | 92 simbol, **2026-05-24 → 2026-10-07** (131 hari) | OHLC + vwap + notional + `buy_n/sell_n` + `buy_qty/sell_qty` + `big_n/big_qty` per (simbol, menit) |
| Binance klines **1 menit** (akan diunduh, `data.binance.vision`, publik) | simbol padanan periode sama | syarat H9 |

Split waktu (BEKU): **IS = 2026-05-24 … 2026-08-31** | **OOS = 2026-09-01 … 2026-10-07**.

Universe (aturan BEKU, dihitung dari IS saja, sebelum hipotesis):
simbol memenuhi **median notional/menit ≥ $100** DAN **≥30% menit punya trade**.
Daftar hasil filter dilaporkan di dokumen HASIL. Tidak ada penyaringan lain.

## 2. Hipotesis (2, terkunci)

### H9 — Lead-lag lintas venue (Binance → SoDEX), resolusi menit
Premis arsitektural: harga SoDEX tertinggal dari referensi global (perp tipis /
oracle lebih lambat). Edge macam ini **hanya bisa ada di venue lambat**, tidak butuh breadth.

- Sinyal: `bl_k = log(C_binance[t]) − log(C_binance[t−k])`, **k ∈ {1, 5, 15} menit**
- Arah: mengikuti tanda `bl_k` (momentum lintas venue)
- Posisi SoDEX menit `t+1 … t+1+H`, **H ∈ {5, 15, 60} menit**
- Mode: **directional SoDEX** (biaya 2 leg) — mode **market-neutral** (SoDEX + short Binance, biaya 4 leg) dilaporkan sebagai informasi, bukan gerbang

### H10 — Order-flow imbalance **native** SoDEX → imbal hasil ke depan
Premis arsitektural: di pasar tipis retail-heavy, arus order itu **sinyalnya sendiri**
(bukan noise seperti di venue dalam). Ini alpha **kepemilikan data** — tape SoDEX
per-menit hanya kita yang punya.

- Sinyal: `ofi_W = Σ(buy_qty − sell_qty) / Σ(buy_qty + sell_qty)` atas **W ∈ {15, 60} menit** terakhir
- Arah: `ofi_W > 0` → LONG, `< 0` → SHORT
- Hold **H ∈ {15, 60} menit**

## 3. Biaya (BEKU)

| Model | per sisi | round-trip | Peran |
|---|---|---|---|
| Taker resmi SoDEX (0,040%) | 4,0 bp | **8,0 bp** | **base** |
| Konservatif (pembacaan ALT3) | 8,0 bp | **16,0 bp** | **stress — WAJIB lolos** |
| Maker (0,012%) | 1,2 bp | 2,4 bp | informasi saja |

Sensitivitas slippage tambahan dilaporkan pada +0/+1/+2/+5 bp per sisi.
Biaya diterapkan **per leg round-trip** (masuk + keluar), bukan sekali.

## 4. Statistik (BEKU)

- **Non-overlapping**: `stride = H`; n dilaporkan sebagai `n_rebal`, bukan jumlah baris.
- **p-value**: **block bootstrap** (blok 60 menit, 2000 resample) — bukan permutasi naif,
  karena return menit berautokorelasi.
- **Multiplisitas**: BH-FDR q=0,10 atas keluarga hipotesis yang diuji (9 sel H9 + 4 sel H10).
- CI95 dilaporkan untuk setiap sel.
- Dedup pasangan (simbol × hari) — satu simbol satu hari dihitung sekali per jendela.

## 5. Kontrol negatif (WAJIB GAGAL kalau harness benar)

| Kode | Kontrol | Syarat |
|---|---|---|
| F-a | Sinyal dibalik (fade) | **harus ≤ 0** |
| F-b | Tanda sinyal diacak **per blok 60 menit dalam simbol-hari** | **p > 0,05** |
| F-c | Panel sintetis random-walk tanpa edge | **tidak boleh lulus** |

## 6. Gerbang keputusan (c1–c6, BEKU — semua wajib)

| # | Syarat |
|---|---|
| c1 | `n_rebal` ≥ 300 **dan** ≥ 60 hari |
| c2 | net > 0 pada biaya **base** (8 bp) |
| c3 | net > 0 pada biaya **stress** (16 bp) |
| c4 | p ≤ 0,05 **dan** lolos BH-FDR q=0,10 |
| c5 | share satu simbol ≤ 30% dari total net |
| c6 | net > 0 di **OOS** pada biaya **stress** |

Lolos semua = "**layak diuji forward**" — BUKAN berarti target 0,8%/48 jam tercapai.

## 7. Yang TIDAK dilakukan

- Tidak menyetel ulang ambang setelah melihat hasil.
- Tidak menambah varian setelah hasil keluar (kalau perlu varian baru → putaran baru, pra-reg baru).
- Tidak menyentuh OOS sebelum keputusan IS dibekukan.
- Tidak mengubah parameter modal/ambang pra-reg lama (`TE_CAPITAL_USD` tetap 30; LOCKBOX lama tetap tersegel).

## 8. Berkas yang akan dibuat

- `scripts/sodex_spec4_micro.py` — harness (H9 + H10 + kontrol F-a..F-c)
- `scripts/sodex_fetch_binance_1m.py` — pengunduh klines Binance 1m (READ-ONLY, publik)
- `tests/test_sodex_spec4_harness.py` — kalibrasi harness
- `reports/sodex/sodex_spec4_*.json` — hasil
- `docs/sodex/SODEX_SPEC4_HASIL_*.md` — laporan hasil + daftar deviasi

— BEKU. Hermes Anantara v3 — 2026-10-07
