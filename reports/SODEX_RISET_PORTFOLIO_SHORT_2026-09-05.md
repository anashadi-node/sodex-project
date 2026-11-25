# SODEX — RISET PORTFOLIO MULTI-POSISI & PAPER SHORT (2026-09-05)

## Bagian 1 — Portofolio Multi-Posisi (riset task-5, Monte Carlo 10k x 30 hari)
### Analisis (data nyata 549 trade, modal $139.37)
| Skenario | E[daily ROI] | P(≥0.7%) | maxDD (p95) | P(ruin) |
|---|---|---|---|---|
| 1 besar BTC L2 | +4.12% | 58.5% | 17.1% (41.6%) | 1.5% |
| **2-3 sedang (SOL+UNI+DOGE) L2** | **+4.93%** | **61.3%** | **15.7% (38.6%)** | **1.0%** |
| 5 kecil L2 | +4.16% | 60.1% | 16.6% (39.8%) | 1.4% |
| Ultra-aman 5xL1 | +2.09% | — | 10.0% (22.4%) | — |

### Verdict investasi
- **2-3 posisi sedang L2 = optimal** (E tertinggi, DD terendah, ruin terendah).
- L3 BERBAHAYA semua skenario (P(ruin) 5-10%, worst-day -20% di 70-75% jalur).
- Margin total ≤70% wallet ($99.30) — sisanya buffer spot + drawdown.
- Edge trio SOL/UNI/DOGE: mean +0.82%/trade, bootstrap CI95 [+0.49%,+1.14%], P>0 100%.

### Implementasi: paper_test_portfolio.py
- **Adaptif**: tiap pair pilih arah (c>SMA50 → LONG, c<SMA50 → SHORT).
- Maks 3 posisi (SOL+UNI+DOGE penentu), L=2, notional $66 → margin $33/posisi.
- TP 2.5%/SL 1.5%, breakeven-trail (SL_PROTECT WR 75.9%), time-stop 30h.
- Service: anantara-paper-portfolio (AKTIF).

## Bagian 2 — Paper SHORT (market sideways-bearish)
### Kenapa penting
User approve: market crypto sekarang sideways cenderung BEARISH (terverifikasi:
BTC/ETH/SOL/DOGE di bawah SMA50, ADX 32-39; UNI satu-satunya BULL +42% 7d).
Perps-short live dimatikan permanen 2026-09-04 (phantom) — perlu data valid dulu.

### FALSIFIKASI PENTING (jujur, scientific)
Backtest signal short-bear 500h TERBARU dengan TP4%/SL2%:
| Pair | n | WR | PF | avg |
|---|---|---|---|---|
| BTC | 4 | 25% | 0.29 | -0.74% |
| ETH | 4 | 50% | 0.46 | -0.83% |
| SOL | 2 | 0% | 0.00 | -1.70% |
| DOGE | 6 | 17% | 0.32 | -0.74% |

**0 TP di semua pair** → TP4% TIDAK tercapai di market sideways (bukan free-fall).
Adaptasi: TP2.5%/SL1.5%/L2 (v2) → masih mayoritas negatif (hanya ETH PF 1.05).
n kecil, TAPI arah konsisten — hipotesis "short-bear profitable" BELUM terbukti.

### Implementasi: paper_test_shortbear.py
- Signal mirror research_short_bear (ADX>25, c<SMA50<SMA200, RSI mid, vol surge,
  24h down, 1h bump), data Binance API live (bukan feather yg hilang).
- TP2.5%/SL1.5%/L2 (berdasarkan falsifikasi), max 3 posisi, 6 pair.
- Service: anantara-paper-shortbear (AKTIF, fire SOL SHORT di market bearish).
- Tujuan: kumpulkan n>=30 forward utk keputusan evidence-based.

## Bagian 3 — Dekomposisi (dari forensik task-4, MSEREPAKAT)
- Dead zone UTC 5/12/17/18 → sdh diimplement di realwide paper (commit 287e68a).
- Pair konsisten profit: BTC/SOL/DOGE/UNI (BH-FDR lolos) — sudah jadi universe baru.
- Hold 8-30 jam sweet spot — time-stop 30h dipertahankan.

## Keputusan LIVE (tetap hati-hati)
- Portfolio & short = PAPER dulu, n>=30, gate WR>=50% + PF>=1.5 + ROI>=0.7%.
- Tidak ada perubahan ke live tanpa bukti forward + approval user.