# RISET MENDALAM: AKURASI PREDIKTIF DI MARKET SIDEWAYS-BEARISH (2026-09-05)
> "Siapa yang selangkah lebih maju membaca arah market dengan cepat & akurat = pemenang."
> Studi menyeluruh: 4 subagent riset + arXiv + jurnal + data internal 549 trades.

## 1. TEMUAN FONDASIONAL (arXiv 2602.11708, Adaptive Portfolio)
Bahkan strategi trend-following TERBAIK di dunia membuktikan:
| Regime | Ann. Return | Sharpe | WR | Avg/Trade |
|---|---|---|---|---|
| Bull | 68.3% | 3.42 | 54.2% | +1.82% |
| Sideways | 18.7% | 1.87 | 47.8% | +0.63% |
| Bear | -4.2% | -0.31 | 41.3% | -0.21% |

=> DI BEAR, RATA-RATA STRATEGI RUGI. Yang terbaik bukan memaksa profit
   tapi MEMBATASI RUGI. Falsifikasi terhadap asumsi "harus profit semua
   regime". Prinsip: jangan melawan arus, matikan saat sideways-bear.

## 2. STATISTIK INTERNAL (n=42 short TWOWAY) — PALING KUAT
- FILTER WAJIB 1: r1h<0 (momentum-fade) — short saat 1h turun: WR 45.5%,
  semua TP. Bounce-chase (-102% total kerugian, p=0.042).
- FILTER WAJIB 2: larang weekend — Sab/Minggu WR 16.7% vs weekday 69%
  (p=0.012).
- Kombinasi weekday+r1h<0: WR 69%, avg +1.05 usd (Fisher p=0.003).
  => SUDAH DIIMPLEMENTASI (commit a9fcf68).

## 3. MITOS TERBANTUHKAN
- Short momentum murni (ADX>25 + bear stack): kalah di sideways
  (backtest 500h: 0 TP).
- Short mean-reversion (RSI overbought dlm bear): kalah juga (WR 25%).
- => Bukan "short salah arah" tapi "short tanpa filter timing + tanpa
  penghormatan weekend" = bunuh diri.

## 4. REGIME-SWITCHING GATE (commit cb33f5c)
Klasifikasi 3-state (BULL/NEUTRAL/BEAR) berbasis EMA50 + r24 + ADX:
- BULL: izinkan LONG
- NEUTRAL: kurangi exposure 50%
- BEAR: HANYA short dgn filter ketat ATAU flat
Verifikasi: BTC turun 1.84%/24h + ADX 26.7 -> BEAR score -0.6.
Terintegrasi gate monitor -> live tahu regime.

## 5. JALUR LANJUT (riset dunia, prioritas utk modal 139)
| Metode | Bukti | Prioritas |
|---|---|---|
| Funding-carry delta-neutral | Elsevier 2025: +115.9%/6bln MDD 1.92% | TINGGI |
| Pair/stat-arb (OU, Hurst<0.5) | Sideways = mode alami | TINGGI |
| RSI-2 Connors dgn filter trend | WR 75-79% dgn filter | SEDANG |
| On-chain flow >2SD | prediksi jual ~72% | SEDANG |
| HMM regime (NHHMM) | deteksi sideway akurat | SEDANG |
| VPIN toxicity | stand-down saat adverse-selection | SEDANG |
=> Semua wajib walk-forward + fee nyata sebelum live.

## 6. KEPUTUSAN
(a) regime gate 3-state membaca market cepat & tidak melawan arus,
(b) filter short statistik (r1h<0 + no-weekend) menaikkan WR 17->69%,
(c) di sideways-bear: PRESERVE CAPITAL > paksa prediksi,
(d) SHORT_BEAR & PORTFOLIO kumpul n30 dengan filter baru.