# PAPER TEST — Akurasi Signal Laporan Pasar-Anantara

- Tanggal: 2026-09-08 · Window: 60 hari · Symbols: 13 (BTC, ETH, SOL, BNB,
  XRP, DOGE, BCH, LINK, AAVE, SUI, TRX, UNI, ENA) · Data: Binance 1h klines
- Metode: replay deterministik `momentum_composite` + `deterministic_direction`
  (pipeline produksi `presentiment_data` / `presentiment_forecast`), dibanding
  vs return close-to-close T+4h/12h/24h. 20% bar terakhir = OOS.

## Hasil (semua horizon)

| Horizon | n | WR% | Base% | ΔWR% | p_binom | OOS_n | OOS_WR% | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 4h | 6215 | 44,3 | 54,1 | **-9,8** | 1,0000 | 1269 | 46,0 | ⚠️ ANTI-PREDICTIVE |
| 12h | 4195 | 41,7 | 57,6 | **-15,9** | 1,0000 | 780 | 42,8 | ⚠️ BIAS STRUKTURAL |
| 24h | 3756 | 38,9 | 60,7 | **-21,8** | 1,0000 | 648 | 37,5 | ⚠️ BIAS STRUKTURAL |

## Temuan Kritis (verified, bukan artifact)

1. **Bias struktural UP impossible** — `momentum_composite` produksi menjenuh
   pada +0,33 max (diverifikasi dengan sintetik uptrend murni / 275 window).
   Threshold 12h dan 24h (0,35 / 0,40) TIDAK PERNAH tercapai oleh pipeline
   ini → **sinyal UP 12h/24h mustahil** (UP12=0, UP24=0 di semua 13 symbol).
2. **Anti-predictive** — WR < base-rate di semua horizon (Δ -9,8 s.d. -21,8pp),
   p_binom mendekati 1 (sinyal lebih buruk dari random). Bukti tambahan:
   saat sinyal DOWN12 (BTC), avg return T+12 = **+0,19%** → arah salah.
3. **Base rate tinggi karena regime** — periode ini harga sebagian besar
   NAIK (base_up 54-61%), sementara pipeline bias memberi sinyal DOWN
   (DOWN88% dari sinyal non-neutral) → kombinasi merugikan.

## Kesimpulan Ilmiah (falsification-first)

**Signal laporan Pasar-Anantara versi deterministik TIDAK AKURAT dan
ANTI-PREDICTIVE pada 60 hari terakhir.** Tidak direkomendasikan dipakai
sebagai dasar keputusan trading. Root cause = desain bias pipeline
(threshold tidak achievable + bobot komposit bias short) + regime mismatch.

## Rekomendasi

1. **Kalibrasi ulang threshold** agar achievable oleh distribusi skor nyata
   (mis. quantile-based, bukan konstanta absolut).
2. **Audit komposisi skor** — EMA(=)→−1 + ADX gate default 0 di ranging
   menjenuhkan skor ke negatif. Pertimbangkan neutral handling for equals.
3. **Tidak dipakai live** sampai backtest jujur menunjukkan ΔWR>0 signifikan
   OOS.
4. Paper test ini jalan otomatis (service `anantara-paper-pasar-anantara`)
   → hasil diperbarui per cycle.

---
*Di-generate oleh Hermes Anantara — jujur, berbasis data, no bias.*