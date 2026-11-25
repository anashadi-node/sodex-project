# SODEX — Robustness Check: Backtest 90-DAY vs 60-DAY (2026-09-09)

## Konklusi
Hasil paper test laporan pasar **ROBUST** — backtest 90-hari (13 symbol,
Binance 1h) konsisten dengan window 60-hari. Antipredictive deterministik
TIDAK artifact ali rezim window spesifik.

## Perbandingan

| Horizon | 60d (Sep-8) | 90d (Sep-9) | Delta |
|---|---|---|---|
| 4h  | WR 44,3% Δ −9,8pp | WR 44,2% Δ −9,9pp | ≤0,1pp |
| 12h | WR 41,7% Δ −15,9pp | WR 41,7% Δ −15,9pp | exact |
| 24h | WR 38,9% Δ −21,8pp | WR 38,9% Δ −21,6pp | 0,2pp |

Semua horizon tetap ANTI-PREDICTIVE / BIAS STRUKTURAL (UP mustahil — score
max +0,33 < threshold 0,35/0,40).

## Implikasi
1. Kesimpulan sebelumnya tetap valid — deterministik momentum_composite +
   deterministic_direction TIDAK prediktif untuk trading.
2. Contrarian oversold (skor ≤ −0.60 → LONG T+24h, OOS +9.1pp) = kandidat
   yang diuji laporan pasar team, bukan SoDEX.
3. Forward tracking (40 prediksi/cycle) terus mengukur akurasi nyata —
   verifikasi pertama due 02:00 UTC.

## File
- Reports: reports/sodex/paper_pasar_anantara_20260909_002226.json (90d)
- Backtest tool: scripts/paper_test_pasar_anantara.py
- Dashboard: http://127.0.0.1:8788 (Pusat Pantau Ekosistem) — section
  "Paper Test Akurasi Signal Laporan Pasar" auto-updates latest report