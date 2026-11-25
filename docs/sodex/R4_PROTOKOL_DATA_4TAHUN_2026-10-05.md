# R4 — PRA-REGISTRASI PROGRAM DATA 4 TAHUN (BINANCE) "MODE METODE LINTAS-REZIM"

**Tanggal beku**: 05 Oktober 2026
**Status**: protokol dibekukan SEBELUM unduh & SEBELUM evaluasi.
**Asal usul**: usulan Mas Anas (05-Okt) — simulasi Strategi/Mode/Metode memakai data
rinci 4 tahun. Dikoreksi dgn bukti ketersediaan data (lihat §1).
**Mode**: READ-ONLY terhadap sistem live. Tidak menyentuh gate/leverage/sizing/target.

---

## 1. Koreksi berbasis bukti — apa yang BISA dan TIDAK BISA

| Venue | Klaim "4 tahun" | Bukti di disk / endpoint | Putusan |
|---|---|---|---|
| **SoDEX** | tidak bisa | orderflow `data/orderflow_capture_*.jsonl` = **2026-08-11 → 2026-10-05 (54 hari)**; `sodex_public_trades.db` = 2026-07-30 → 2026-08-02 (**3 hari**); tidak ada endpoint historis per-pair | **MUSTAHIL** — lane SoDEX tetap hanya sah di **jendela forward** (T1) |
| **Binance** | bisa | arsip `data.binance.vision` 2022-10 (futures klines, spot klines, fundingRate) = **HTTP 200**; `fapi` = HTTP 200; data lokal sekarang 2025-03-17 → 2026-10-03 | **BISA** — unduh 48 bulan |

Catatan jujur: 4 tahun data Binance **tidak** membuat lane SoDEX bisa diuji. Dua venue
tetap dipisah; klaim lintas-venue hanya sah bila data masing-masing venue ada.

## 2. Spesifikasi data — DIBEKUKAN

- **Rentang**: `2022-10-01` → `2026-10-05` (48 bulan, mencakup bear-2022, chop-2023, bull-2024/25).
- **Universe DIBEKUKAN (11 major, tercatat ≥4 tahun di Binance USDM & Spot)**:
  `BTC ETH SOL BNB XRP DOGE ADA AVAX LINK DOT LTC`
- **DIKELUARKAN** (listing <4 tahun, mencegah bias survivorship): SUI, ARB, INJ, NEAR, ASTER, LIT.
  Konsekuensi jujur: engine yang bergantung pada pair kecil **tidak** dapat diuji di program ini.
- **Data yang diunduh**: futures 1h/4h/1d, spot 1h/4h/1d, funding rate 8h, mark price 1h.
- **Manifest**: setiap berkas dicatat ukuran + sha256 di `reports/sodex/R4_dataset_manifest.json`.

## 3. Pemecahan data (LOCKBOX) — DIBEKUKAN

| Blok | Rentang | Aturan |
|---|---|---|
| **DEV** | 2022-10-01 → 2025-09-30 (36 bln) | walk-forward: latih 6 bln / uji 3 bln, jendela uji **non-overlap** → 12 kuartal uji |
| **LOCKBOX** | 2025-10-01 → 2026-10-05 (12 bln) | **TIDAK disentuh** sampai hipotesis dibekukan; dibuka SEKALI per hipotesis, hasil apa pun dilaporkan |

Melanggar lockbox (mengintip lalu merevisi hipotesis) = pelanggaran protokol; wajib dilaporkan.

## 4. Hipotesis yang diuji — DIBEKUKAN (maks 5; BH-FDR atas kelimanya)

| # | Hipotesis | Sumber mesin di sensus D14 |
|---|---|---|
| H1 | Momentum/trend continuation SOL & majors, horizon 48 jam | `spot_swing_cex`, `realwide` |
| H2 | Breakout Donchian 4h/1d, horizon 48 jam | `donchian` |
| H3 | Funding-carry delta-neutral lintas-venue, horizon 48 jam | `mv_funding` |
| H4 | Mean-reversion setelah ekstrem volatility (vol-gated), horizon 48 jam | varian gate volatilitas |
| H5 | Regime-gated composite (BULL/BEAR/CHOP berbeda aturan), horizon 48 jam | `twoway`, `hmm_regime` |

Interpretasi parameter & grid: **dideklarasikan di berkas hipotesis terpisah SEBELUM uji**;
jumlah percobaan (trials) dicatat untuk koreksi DSR/PBO.

## 5. Ambang putusan — DIBEKUKAN (sama keluarga dgn P9 agar dapat dibandingkan)

| Putusan | Syarat (per hipotesis, pada 12 kuartal DEV) |
|---|---|
| **PASS** | n_jendela ≥ 20 **∧** SR tahunan ≥ 2,3 **∧** 3/3 segmen positif **∧** p_worst < 0,05 **∧** BH-FDR q=0,10 **∧** 2× biaya masih > 0 **∧** PBO < 20% **∧** DSR > 0 |
| **FAIL** | syarat di atas tidak terpenuhi pada DEV |
| **LOCKBOX** | hanya HIPOTESIS YANG PASS di DEV boleh dibuka lockbox-nya, sekali |

**PASS di R4 BUKAN izin live.** Promosi tetap menuntut T1–T6 + approval user.

## 6. Kontrol anti-overfit (mengikat)

1. Ambang, universe, dan pemecahan blok tidak diubah setelah hasil keluar.
2. Setiap hipotesis wajib lulus **kontrol acak** (deret acak mean/sd sama) sebagai pembanding.
3. Biaya wajib 2× (fee riil + slippage 5 bps majors) tetap positif.
4. Jumlah trials dicatat; DSR/PBO dihitung dari jumlah itu (bukan dari satu percobaan terbaik).
5. Tidak ada "parameter terbaik dari 100 percobaan" tanpa koreksi — hasil mentah ikut dilaporkan.

## 7. Yang TIDAK dibuktikan oleh R4 (batas jujur)

- Kualitas eksekusi nyata 2022 ≠ 2026 (spread/depth berubah) — R4 hanya membuktikan **struktur statistik**.
- Lane SoDEX tidak tersentuh (data venue hanya 54 hari) → tetap menunggu jendela forward.
- Pair kecil & listing baru tidak terwakili.
- Hasil R4 tidak mengubah target 0,8%/48j dan tidak melonggarkan batas keamanan mana pun.

## 8. Produk

- `reports/sodex/R4_dataset_manifest.json` — manifest + sha256 tiap berkas.
- `reports/sodex/R4_<hipotesis>_DEV.md` — hasil DEV per hipotesis (+ kontrol acak, DSR, PBO).
- `reports/sodex/R4_LOCKBOX_<hipotesis>.md` — hasil lockbox sekali buka.

---

*Dibekukan 05-Okt-2026 · Hermes Anantara v3 · Target 0,8%/48j harga mati; gate T1 utuh;
tanpa leverage; SODEX_TOTAL_WALLET tidak diubah; E1 beku; arm A1 mati; RW_MARGIN_UTIL_CAP OFF.*
