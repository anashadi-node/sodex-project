# SODEX — PROGRES & PERSIAPAN LIVE TRADING 2026-09-05

## Audit sebelum lanjut (semua terverifikasi)
- 8 paper track AKTIF, 2 live AKTIF, perps-short OFF.
- Watchdog 0 CRITICAL, sync realtime match 100%.
- 39 test suite pass (23 fail pre-existing di modul lama).
- ***** Temuan baru *****: deep learner terkontaminasi phantom
  (spot_live + perps_short) → dibersihkan 337→328 trade (commit 7648fa8).

## Status paper (denominator jujur $139,37)
| Track | n | WR | ROI | Target 0.7% |
|---|---|---|---|---|
| REALWIDE | 62 | 50% | +1.507% | ✅ |
| TWOWAY LONG | 108 | 54.6% | +1.187% | ✅ |
| SWING | 142 | 46.5% | +0.567% | dekat |
| SWING_PARTIAL | 137 | 56.9% | +0.564% | dekat |
| SPOT_V4 | 10 | 50% | +0.451% | ❌ (n kecil) |
| DONCHIAN | 48 | 37.5% | -0.289% | ❌ |

## Persiapkan live
- REALWIDE live AKTIF: $50@3x, TP4%/SL2 (maturasi), macro-gate BLOKIR
  sementara (BTC < SMA50) — sistem disiplin.
- SPOT live AKTIF: $6/trade, posisi BTC -0,27% dikelola exit engine.
- 5 subagent riset PARALEL jalan (entry-timing, sizing, metode web,
  forensik, portfolio) — hasil akan masuk setelah selesai.

## Langkah berikutnya (setelah riset masuk)
1. Terapkan temuan entry-timing jika signifikan (p<0.05 BH).
2. Evaluasi hasil portfolio → konfigurasi posisi optimal.
3. Maturasi paper TP6/SL1.5 → n≥30 → promosi live.
4. GO-LIVE saat gate LONG terbuka lagi (BTC recovery).