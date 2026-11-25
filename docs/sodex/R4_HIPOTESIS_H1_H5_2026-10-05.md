# R4 — SPESIFIKASI HIPOTESIS H1–H5 (DIBEKUKAN SEBELUM UJI)

**Tanggal beku**: 05 Oktober 2026
**Disetujui**: Mas Anas, 05-Okt ("setuju H1–H5")
**Aturan mengikat**: parameter di bawah **TIDAK diubah** setelah hasil keluar. Tidak ada
pencarian grid. Tiap hipotesis = SATU spesifikasi (bukan keluarga). Jumlah percobaan = 5
(untuk koreksi BH-FDR). Semua horizon 48 jam, jendela non-overlap, 2× biaya.

**Biaya (dibekukan)**: taker fee 0,05% per sisi (Binance USDM) + slippage 5 bps per sisi
(major likuid) → **total 0,20% per trade** (masuk+keluar), dibayar **2×** = 0,40% (aturan
program: "biaya wajib 2× tetap positif"). H3 (carry) = 2 kaki × (fee+slippage) = 0,40%,
juga 2×.

**Data**: `data/r4/binance` (Binance) — DEV 2022-10-01..2025-09-30; LOCKBOX
2025-10-01..2026-09-30 **tidak disentuh** di fase ini. Universe 11 major. Bar 1h dari
arsip bulanan; 4h/1d dari arsip yang sama.

---

## H1 — Momentum/trend continuation (48 jam)

- **Sinyal masuk** (evaluasi tiap 1 jam, hanya saat tidak ada posisi):
  - LONG bila `close > SMA200(1h)` **dan** `ret24 = close/close[-24h] − 1 > 0`
  - SHORT bila `close < SMA200(1h)` **dan** `ret24 < 0`
  - selain itu: FLAT (tidak ada trade)
- **Keluar**: tepat 48 jam setelah masuk (waktu, bukan harga). Tidak ada stop/TP (menjaga
  spesifikasi tunggal; risiko ekor dicatat, bukan dikelola di sini).
- **PnL per trade**: `arah × (exit/entry − 1) − 0,004`
- **Coin**: tiap major dinilai sendiri; portofolio H1 = rata-rata lintas coin.

## H2 — Breakout Donchian (4h, horizon 48 jam)

- **Sinyal masuk** (bar 4h): LONG bila `close > max(high, 48 bar 4h terakhir)`;
  SHORT bila `close < min(low, 48 bar 4h terakhir)`. Satu posisi pada satu waktu.
- **Keluar**: 48 jam setelah masuk.
- **PnL**: `arah × (exit/entry − 1) − 0,004`

## H3 — Funding-carry delta-netral (48 jam) — *proksi*

- **Sinyal**: bila `funding_rate 8h > 0` (perp bayar ke short) → SHORT perp; hedge spot
  diasumsikan biaya pinjam 0 (proksi; batas dicatat di laporan).
- **Keluar**: 48 jam (6 periode funding 8 jam).
- **PnL**: `Σ funding 6 periode − 0,004` (dua kaki × 2× biaya).
- Catatan jujur: proksi ini **tidak** memodelkan basis risk, biaya pinjam spot, atau
  eksekusi kaki kedua; hasilnya batas atas optimistis, dilaporkan apa adanya.

## H4 — Mean-reversion setelah lonjakan volatilitas (48 jam)

- **Sinyal**: `z = (ret48 − mean(ret48, 720h)) / sd(ret48, 720h)`;
  LONG bila `z < −2` **dan** `ATR%(14, 4h)` berada di desil ≥ 0,8 dari 720 jam terakhir;
  SHORT bila `z > +2` dengan filter vol yang sama; lainnya FLAT.
- **Keluar**: 48 jam. **PnL**: `arah × (exit/entry − 1) − 0,004`

## H5 — Composite bergantung rezim (48 jam)

- **Rezim** (dari 4h): BULL bila `SMA200(4h) naik` (slope 48 jam > 0) **dan**
  `close > SMA200(4h)`; BEAR bila kebalikannya; sisanya CHOP.
- **Aturan**: BULL → pakai sinyal LONG H1; BEAR → pakai sinyal SHORT H1; CHOP → FLAT.
- **Keluar**: 48 jam. **PnL**: `arah × (exit/entry − 1) − 0,004`

---

## Ambang putusan (dari R4 §5, tidak diubah)

PASS bila seluruhnya benar pada DEV:
`n_jendela ≥ 20` ∧ `SR tahunan ≥ 2,3` ∧ `3/3 segmen positif` ∧ `p_worst < 0,05`
∧ `BH-FDR q=0,10` ∧ `2× biaya masih > 0` ∧ `PBO < 20%` ∧ `DSR > 0`.

**p_worst = maks(p_signflip, p_day_cluster).** Jendela = grid 48 jam non-overlap mulai
2022-10-01 00:00 UTC di atas **portofolio lintas-coin** (rata-rata 11 major, bobot sama).

## Kontrol wajib

Deret acak dengan mean & sd sama (seed 20261005, 20.000 simulasi) harus **kalah** atau
paling tidak tidak kalah signifikan; kalau kontrol menang → hipotesis ditolak.

## Yang tidak dibuktikan fase DEV

- Kinerja di LOCKBOX (belum dibuka).
- Eksekusi nyata & mikro-struktur SoDEX (hanya venue di R4 yang punya data).
- PBO/DSR dihitung pada fase ringkasan setelah 5 hipotesis selesai.

---

*Dibekukan 05-Okt-2026 · Hermes Anantara v3 · target 0,8%/48j tidak diubah;
gate T1 utuh; tanpa leverage; SODEX_TOTAL_WALLET tidak diubah; E1 beku; arm A1 mati.*
