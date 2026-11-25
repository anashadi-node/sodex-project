# HASIL UJI ALTERNATIF TOP-4 (SODEX-ALT1) — 2026-10-07

**Pra-registrasi:** `docs/sodex/SODEX_ALT_TOP4_PRAREG_2026-10-07.md` (ambang beku, §6/§6b).
**Venue uji:** Binance USDT-perp 1-menit → bar 4H & harian, **11 simbol × 36 bulan**
(Okt 2022 – Sep 2025). IS 2022-10-01..2024-11-30 · OOS 2024-12-01..2025-09-30.
**Biaya:** taker Binance 4,5 bp/leg → round trip **9 bp**; diuji juga **1,5×** (13,5 bp).
**Harness:** `scripts/binance_alt_top4_study.py` · kontrol negatif random-entry/random-ranking.

---

## 1. VERDICT: **0 dari 17 varian LAYAK** (gagal syarat pra-registrasi §2)

| Varian (OOS) | n | net (bp) | stress (bp) | WR | p | simbol dominan | Gagal di |
|---|---|---|---|---|---|---|---|
| h1_LONG (breakout ↑) | 563 | +12,3 | +7,8 | 47,2% | **1,000** | ADA 56% | c4, c5 |
| h1_SHORT (breakout ↓) | 492 | −14,8 | −19,3 | 48,4% | 1,000 | ETH −16% | c2, c3, c4 |
| h2_LONG (OFI desil atas) | 5466 | −3,4 | −7,9 | 48,1% | 0,152 | AVAX −21% | c2 |
| h2_SHORT (OFI desil bawah) | 5466 | −9,4 | −13,9 | 46,9% | 0,858 | DOGE −7% | c2 |
| h3_LONG / h3_SHORT | 5463 | −2,2 / −10,9 | − | 48,8% | 0,16/0,96 | — | c2 |
| h6_LONG / h6_SHORT | 5454 | −0,6 / −14,7 | − | 48,8% | 0,37/0,99 | — | c2 |
| h12_LONG (48 jam) | 563 | +144,6 | +140,1 | 54,7% | **1,000** | ETH 20% | c4 |
| h12_SHORT | 492 | −112,2 | −116,7 | 41,3% | 0,002 | SOL −2% | c2, c3 |
| h7_LONG (momentum 7h) | 1188 | **+52,9** | +48,4 | 46,5% | **0,017** | **ETH 64%** | c5 |
| h7_LONG_upup (gate UP→UP) | 720 | +41,1 | +36,6 | 42,9% | 0,050 | ETH 121% | c5 |
| h7_SHORT | 1188 | −7,7 | −12,2 | 52,1% | 0,060 | ETH −96% | c2, c5 |

Syarat: c1 n≥100 · c2 net>0 · c3 tetap>0 di biaya 1,5× · c4 p<0,05 · c5 kontribusi satu simbol ≤30%.

## 2. Harness terbukti sah (wajib sebelum mempercayai "0 lulus")

`tests/test_binance_alt_harness.py` — **6 tes LULUS**:
1. Sinyal tanpa edge → **tidak** menghasilkan p kecil palsu (20 seed; tingkat false-positive ≤15%).
2. Edge +100 bp yang disuntikkan → **terdeteksi** (p < 0,05). Harness mampu melihat edge.
3. **Regresi penting:** kontrol SHORT wajib *sign-aware*. Versi pertama harness membandingkan
   `fwd` mentah → pada pasar yang naik, SHORT rugi terbaca "signifikan" padahal wajar. **Bug ini
   ditemukan & diperbaiki sebelum hasil akhir.** Tanpa perbaikan, laporan akan berbohong.
4. Kontrol ranking sign-aware.
5. Varian yang **rugi** tapi p kecil **tidak** boleh dianggap LAYAK.
6. Varian yang bergantung **satu simbol** ditolak.

## 3. Interpretasi jujur per strategi

**#1 External-Regime Adaptive Breakout — TIDAK DIDUKUNG.**
h12_LONG tampak +144,6 bp, tetapi p = **1,000**: entry breakout justru **lebih buruk** daripada
entry acak pada hari-simbol yang sama. Artinya angka +144 bp itu **drift pasar**, bukan skill timing.
Sisi SHORT rugi (−112 bp). Jadi keluarga breakout-terarah-tren **tidak punya edge** di data ini.

**#2 Order Flow (lokal, M1) — TIDAK DIDUKUNG.**
Semua horizon **negatif** (−0,6 s/d −14,7 bp). Ini uji yang paling bertenaga (n ≈ 5.460 per varian),
jadi hasil negatif ini **kuat**, bukan kekurangan sampel.

**#4 Risk-Managed Regime Momentum — MENGGUMPULKAN, tapi TIDAK ROBUST.**
h7_LONG: +52,9 bp per 7 hari, p = 0,017, tahan biaya 1,5×. **Tetapi** kontribusi **ETH = 64%**
dari total net (syarat ≤30%). Tanpa ETH, edge-nya tidak jelas. Gate UP→UP tidak memperbaiki
(ETH = 121% — lebih buruk).

## 4. Pengamatan pasca-hoc (BUKAN klaim — perlu pra-registrasi baru)

Kedua sisi breakout bergerak ke arah yang sama dan berlawanan dengan premis #1:

- `h1_LONG` p = 1,000 → setelah breakout **naik**, harga **underperform** vs acak.
- `h1_SHORT` p = 0,002 → setelah breakdown, `fwd` **di atas** acak (harga justru naik).

**Keduanya menunjuk hal yang sama: breakout ekstrem cenderung MEAN-REVERT, terutama di 48 jam.**
Ini **hipotesis yang dihasilkan data**, bukan edge terkonfirmasi — arahnya dipilih *setelah*
melihat hasil, sehingga **tidak sah** sebagai konfirmatori di data yang sama.
Verifikasi harus di venue **independen** (SoDEX, BTC/ETH/SOL) dengan pra-registrasi baru.

## 5. Batas jujur laporan ini

- Ini **data Binance, bukan SoDEX**. Hasil negatif di sini tidak otomatis berarti gagal di SoDEX;
  hasil positif pun tidak membuktikan SoDEX profitable.
- **Open Interest tidak tersedia** → overlay OI di dokumen acuan di-drop, bukan diuji.
- Funding diabaikan (tidak tersedia lintas-rezim di Binance yang diunduh).
- **#3 ProSP tidak diuji** (butuh pipeline ML cross-sectional + OI yang tidak tersedia).
- Yang terjawab: **Top-4 seperti dispesifikasikan tidak menunjukkan edge bersih & robust di data
  ini.** Yang TIDAK terjawab: apakah target 0,8%/48 jam bisa dicapai dengan pendekatan lain.

## 6. Rekomendasi falsifiable berikutnya

1. **Pra-registrasi baru H5 (mean-reversion pasca-breakout)** — arah eksplisit long-setelah-breakdown
   / short-setelah-breakout, horizon 48 jam; uji di **SoDEX** (venue independen, 126 hari, 3 simbol).
   Falsifier: net ≤ 0 setelah biaya atau p ≥ 0,05 → H5 gugur.
2. **Tunggu replikasi SoDEX 92 simbol** (matang ≈ 2 minggu) sebelum menyimpulkan apa pun tentang
   strategi lintas-seksi di SoDEX.
3. **Jangan** menyimpulkan target tak tercapai hanya dari laporan ini; **jangan** juga mengklaim
   ada strategi yang berhasil — keduanya belum terbukti.
