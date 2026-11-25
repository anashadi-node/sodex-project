# PRAREG-P3 — Arbitrase Dislokasi SoDEX × Binance USDM

**Dibekukan:** 25 Okt 2026, 15:50 UTC — **sebelum** satu pun snapshot buku Binance dikumpulkan.
**Status:** aktif. Amandemen hanya boleh dicatat sebelum analisis, tidak setelah melihat hasil.

## 1. Hipotesis (falsifiable)

**H1:** Pada 10 simbol yang direkam, dislokasi harga SoDEX vs Binance USDM melebihi
biaya dua venue (≥17,6 bps) cukup sering (≥50 event unik / 7 hari) **dan** kembali
ke ≤3 bps dalam ≤2 jam, sehingga rata-rata net per event > 0.

**H0 (yang harus dibunuh):** frekuensi <20 event/7 hari, atau net mean ≤0, atau
waktu revert >2 jam pada mayoritas event.

## 2. Definisi sinyal (beku)

Pada snapshot tersinkron (selisih ≤15 detik):

- **Arah A (beli SoDEX, jual Binance):** `gross = (bnBid / soAsk − 1) × 10⁴`
- **Arah B (jual SoDEX, beli Binance):** `gross = (soBid / bnAsk − 1) × 10⁴`

Trigger bila `gross ≥ 17,6 bps` **dan** notional di best level kedua venue ≥ $250.

## 3. Biaya (beku)

| Komponen | bps |
|---|---|
| SoDEX taker, per leg | 2,80 |
| Binance USDM taker, per leg | 4,00 |
| Slippage, per leg | 1,00 |
| **Total round-trip (4 leg)** | **13,60 fee + 4,00 slip = 17,60** |

Size $250/leg, modal terpakai $500 (dua venue). Return dihitung terhadap $500.

## 4. Eksekusi & exit (beku)

- Entry: taker kedua leg pada snapshot sinyal (asumsi simultan; risiko leg risk dicatat).
- Exit: basis ≤3 bps **atau** 2 jam, mana lebih dulu; exit taker dua leg.
- Tidak ada averaging, tidak ada penambahan saat dislokasi melebar.

## 5. Statistik & verdict (beku)

- Deduplikasi: satu event per (simbol × arah) per 30 menit — bukan hitung tiap snapshot.
- Keputusan butuh **n ≥ 50 event unik**.
- Bootstrap CI95 (10.000 resample) atas net bps; promosi bila **batas bawah CI > 0**
  dan t ≥ 2,5 (layar) — ambang bukti penuh tetap t ≥ 4,11.
- BH-FDR pada 2 arah.
- **Fail-closed:** data <24 jam atau n<50 → `INSUFFICIENT` (bukan PASS, bukan FAIL).

## 6. Yang membatalkan lebih awal (kill rule)

- Setelah 50 event: net mean ≤0 → **tutup**.
- Median waktu revert >2 jam → **tutup** (bukan arb, tapi taruhan basis).
- Kedalaman best level <$250 pada >50% sinyal → **tutup** (tidak executable).

## 7. Keterbatasan yang diakui sejak awal

- Leg risk: dua venue tidak atomik; kegagalan satu leg = posisi telanjang.
- Biaya transfer/withdraw antar-venue tidak dimodelkan (modal diasumsikan sudah terparkir di dua venue).
- Funding perp selama holding tidak dimodelkan (hold ≤2 jam, efek kecil tapi dicatat).
- Data SoDEX berasal dari satu rekaman 51 hari; rezim stress bisa berbeda.
