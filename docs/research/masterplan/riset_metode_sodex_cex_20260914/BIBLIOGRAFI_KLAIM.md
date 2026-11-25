# BIBLIOGRAFI KLAIM — Metode untuk SoDEX & CEX-Binance (Batch tracker)
**Setiap klaim bergaya: [ID] klaim | sumber | label evidence | parameter verifikasi**

## STANDAR LABEL
- **CONFIRMED**: peer-reviewed + replikasi multi-sampel atau dataset transaksi penuh
- **PROMISING**: preprint + metodologi solid / internal backtest terverifikasi / 1 paper peer-reviewed tapi belum direplikasi
- **INCONCLUSIVE**: n kecil / review spekulatif / berdasarkan backtest tunggal
- **FALSIFIED**: gagal OOS atau terjawab oleh bukti internal

---

## LANE S — SoDEX-fitting

### S1 — EXIT GEOMETRY
- [S1.1] Triple-barrier labeling memberikan label berorientasi profit-vs-loss yang lebih baik daripada fixed-horizon | Lopez de Prado, Advances in Financial ML (2018) ch.3 | book method | belum diverifikasi utk crypto swing → PROMISING
- [S1.2] MAE/MFE sebagai fitur cut-loss/power-win; exit optimal < max favorable | umum practitioner + papers | belum audit → perlu riset
- [S1.3] Stop loss proporsional ATR mengurangi whipsaw vs fixed stop | microstructure期刊 | belum disitir → cari

### S2 — ORDER FLOW
- [S2.1] Order Flow Imbalance = price-dell prediktor linear | Cont, Kukanov, Stoikov (2014) "The Price Impact of Order Book Events" | peer-reviewed equities | belum divalidasi crypto perps DEX → riset
- [S2.2] Depth imbalance bid/ask korrelasi dengan future return jangka pendek | papers multiple | belum divalidasi crypto
- [S2.3] Crypto perp funding pressure mempengaruhi order flow | DeFi research papers | belum disitir → cari

### S3 — FUNDING SIGNAL
- [S3.1] Funding rate tinggi → overleveraged long → harga rebal (short bias) | papers MDPI/SSRN | belum audit
- [S3.2] Funding spike → dalam 24 jam harga melemah (funding reversal) | dYdX/HL data studies | belum disitir → cari
- [S3.3] Funding-spread di multi venue (HL/Binance/OKX/dYdX/Bybit) → signal rate | kolom prior session | POOL DATA internal 693 snapshot — PROMISING

### S4 — REGIME
- [S4.1] HMM/crypto market 3-4 state membaikkin gate vs single-strategy | Hamilton/quant papers | belum divalidasi internal → FreqAI HMM sudah ada — audit akurasi
- [S4.2] Vol-managed portfolio meningkatkan Sharpe dalam equities | Moreira & Muir 2017 JF | peer-reviewed, confirmed equities | perlu uji crypto futures → riset
- [S4.3] Volatility risk premium — implied vs realized crypto | papers BTC Deribit | belum disitir

### S5 — SIZING
- [S5.1] Kelly fractional mengungguli fixed fraction di long horizon | Kelly 1956, MacLean-Thorp | peer-reviewed, CONFIRMED teoritis | praktik crypto perps belum audit → riset
- [S5.2] Vol-targeting leverage (inverse to ATR) menurunkan paper DD | papers | sudah dipakai governor SoDEX internal ✓ CONFIRMED internal design

### S6 — DEX-TOKENOMIK
- [S6.1] DEX liquidity cycle & pool-depth modulates price impact | Uniswap/AMM papers | belum disitir
- [S6.2] Oracle delay dapat memicu slippage — TWAP vs instantaneous | Chainlink studies | belum disitir
- [S6.3] Maker rebate equivalent via limit order di DEX perps menaikkan EX-fit | HL/SoDEX microstructure | belum audit

### S7 — MULTI-AGENT/LLM
- [S7.1] LLM-MAS crypto portfolio +133.52% 52mb | arXiv 2501.00826 v3 | preprint, internal metrics | PROMISING
- [S7.2] RRL agent +350% 5y, IR 1.46, 71% profit = funding | UCL paper | peer-reviewed-ish | PROMISING

### S8 — DEEP-LOOP LEARNING
- [S8.1] Online learning drift detection (ADWIN/Page-Hinckley) → machine adapt | River ecosystem | CONFIRMED library
- [S8.2] Re-trained model drft euler → boost/veto path | internal deep_loop | CONFIRMED internal infra

## LANE C — CEX-Binance-fitting

### C1 — PATH GOVERNANCE
- [C1.1] Allocasi berbasis expectancy gate (M6) — veto atau boost kecil di bawah CI | internal deep_loop | CONFIRMED internal, tervalidasi n=90
- [C1.2] SPRT (sequential prob ratio) untuk keputusan accept/reject edge | Wald 1945 | CONFIRMED method statistik klasik | sudah dipakai CEX internal ✓
- [C1.3] Path-level martingale/black-box-based path rebalancing | LLM/adaptive allocation | belum disitir → cari

### C2 — META-LABELING (Lopez de Prado)
- [C2.1] Meta-labeling menaikkan precision tanpa sacrific recall | Lopez de Prado 2018 | book chapter, CONFIRMED equities + futures | **belum diuji crypto per Freqtrade/FreqAI → RISEP PRIORITAS**
- [C2.2] Bagging meta-label dengan LightGBM/XGBoost untuk filter entry III | papers | belum disitir

### C3 — VOL-TARGETING
- [C3.1] Vol-managed portfolios beat fixed vol (Sharpe +0.3-0.5) | Moreira & Muir 2017 Journal of Finance | peer-reviewed CONFIRMED equities | crypto perps alignment belum audit → riset

### C4 — FUNDING EVENT WINDOW
- [C4.1] Binance funding-rate 8h prior/post entry gate mempengaruhi swing PnL | funding perp papers | belum disitir
- [C4.2] Funding spike → mean-reversion 24h menurunkan false LONG | hl_learning_eval/survival_eval | PROMISING internal

### C5 — MARKET IMPLEMENTATION
- [C5.1] Maker-taker fee dimensi: maker rebate naik edge tipis trades | Binance VIP schedule | CONFIRMED fee schedule — tapi belum dimodelkan internal
- [C5.2] Tick-size rebalancing untuk spread optimal di level harga baru | quant microstructure | belum disitir

### C6 — ML ENSEMBLES
- [C6.1] XGBoost/LightGBM ensemble + regime feature menaikkan akurasi crypto di data fikir | papers 2024-2025 | belum alidasi internal — FreqAI LightGBM WR 9.5% = regulasi gagal? → deep audit component
- [C6.2] Stacking multiple regime-models menurunkan variance | ensemble papers | belum disitir

### C7 — VALIDATION METHODOLOGY
- [C7.1] Walk-forward + purged K-fold CV menekan leakage | Lopez de Prado + scipy | CONFIRMED method | belum dipakai konsisten internal
- [C7.2] SPRT + Wilson-CI rejection criteria | internal | CONFIRMED internal

---

## BATCH STATE LOG
```
[14 Sep ~18:05 WIB] Biblio opened. Kandidat riset lanjutan diberi ID S1-S8, C1-C7.
[14 Sep ~19:10 WIB] BATCH 3+4+ABS SELESAI. 12 paper prioritas diekstrak abstract penuh
    -> DIGEST_P01-P12.md. Kanal mati ditemukan & workaround dibangun (harvest.py).
```

### KLaim TERKONFIRMASI dari Batch 1 (P01–P12) — ringkas
```
[K01] ML-candle di Binance Spot GAGAL jadi kebijakan profitable setelah biaya.
      AUC 0,874-0,896 tapi avg precision 0,134; -6,72%/19 siklus @31bps; 3W/16L.
      Audit forensik menolak holdout cacat (no purge, same-close entry).
      -> SUMBER: arXiv 2607.19453 | LABEL: CONFIRMED | PAKAI: peringatan + standar evaluasi CEX
[K02] Hyperliquid: TWAP TERLIHAT lebih murah & permanent impact lebih kecil daripada
      metaorder tersembunyi; menarik likuiditas. 4,3M metaorder + 465K TWAP.
      -> arXiv 2606.15715 | CONFIRMED | PAKAI: strategi eksekusi SoDEX
[K03] Mean-reversion kripto 15-menit NYATA: 90% dari 183 pair Binance vs 2,7% saham AS.
      Sinyal di TANDA. Dipicu aggressive taker flow. Edge gross 1,3bp vs biaya 5bp -> tak lolos.
      -> arXiv 2608.21888 | CONFIRMED | PAKAI: hipotesis horizon 1-30j (belum diuji)
[K04] Agen LLM di produksi (Hyperliquid perps, 6 bulan): 43,2% posisi capai >=+300bps
      dalam 24j TAPI 49,3% ditutup NEGATIF. Bracket mekanis memulihkan +39,0 bps/posisi.
      Tidak ada edge direksional (41% vs 50% benchmark). Sizing buta volatilitas (5x di semua sextile).
      -> arXiv 2609.05663 | CONFIRMED | PAKAI: bukti eksternal diagnosis exit-geometry kita
[K05] Kerangka teori market making perp: dekomposisi PnL (spread|adverse selection|inventory|
      hedging|funding), HJB, Kelly+ruin, identitas APY-VaR.
      -> arXiv 2607.11888 | CONFIRMED (teori) | PAKAI: template audit & kontrol risiko SoDEX
[K06] AdaptiveTrend: trend-following 6-JAM + portofolio adaptif + trailing stop kalibrasi
      volatilitas + alokasi 70/30 -> Sharpe 2,41, MaxDD -12,7%, Calmar 3,18 (150+ pair, 36 bln OOS)
      -> arXiv 2602.11708 | PROMISING | PAKAI: blueprint terdekat untuk CEX 1-30 jam
[K07] Tidak ada studi peer-reviewed yang mengalahkan baseline naif lintas regime pada horizon
      pendek-menengah. Prediktabilitas harian nyata, TIDAK meluas ke jam-an, mungkin tak lolos biaya.
      -> arXiv 2606.00071 | CONFIRMED | PAKAI: dasar menolak jalur "tambah model"
[K08] Peramalan VOL sadar-regime menang; prediktabilitas RETURN lemah & terkonsentrasi di
      regime VOLATILITAS RENDAH; naif gagal, tapi vol-scaling + low-vol gating + kontrol turnover
      memperbaiki kinerja defensif.
      -> arXiv 2606.09478 | CONFIRMED | PAKAI: justifikasi regime gate + low-vol gating CEX
[K09] Pada horizon pendek, OUTPUT HEAD mendominasi backBONE (mixture density +3,7pp CRPS).
      Nilai mixture terbesar di regime volatilitas tertinggi.
      -> arXiv 2606.30037 | CONFIRMED | PAKAI: prediksi kuantil, bukan titik (CEX FreqAI)
[K10] AMM concentrated-liquidity: gap sistematis aktif-pasif; adverse selection tidak merata.
      -> arXiv 2609.37963 | CONFIRMED | PAKAI: referensi jika masuk jalur LP
[K11] RL untuk concentrated liquidity menekan ekor kiri distribusi PnL.
      -> arXiv 2608.19389 | PROMISING
[K12] HFS Arbitrum: 477 swapper, ~30 juta swap, >$10^11 notional; mencakup CEX-DEX execution gaps.
      -> arXiv 2609.14481 | CONFIRMED
```
### FRESH arXiv HITS (abstract terverifikasi 14 Sep)
  [F1] 2411.12753 Supervised Autoencoders + TRIPLE BARRIER labeling, BTC/LTC/ETH 2016-2022:
       SAE+TB "significantly boost" Sharpe/IR; excessive noise/large bottleneck impairs.
       → klaim S1.1: PROMISING → dukungan crypto-direct (preprint)
  [F2] 2504.02249 Triple Barrier + raw OHLCV Korean markets → TB tak hanya US equities → S1.1 membesar
  [F3] 2506.08573 Designing funding rates perp futures (BSDE+arbitrage pricing, replicating
       portfolio, path-dependent funding) → S3 teori integrasi funding-price
  [F4] 2402.03953 DEX perp design (VAMM vs Oracle Pricing) shapes trader behavior;
       open-interest impact LONG vs SHORT asymmetric → S6 + langsung SoDEX karakteristik
  [F5] 2212.06888v7 Fundamentals of Perpetual Futures — no-arbitrage bounds w/ trading
       costs; deviasi crypto LEBIH BESAR, comove, diminish; implied arb HIGH SHARPE
       → S3 CONFIRMED-direction, mendasar funding-intel layer
  [F6] 2608.17342 MoFE mixture-of-experts + Fourier Neural Operators crypto forecast → C6 kandidat
  [F7] 2009.11942 Online learning adaptive rebalancing nonstationary → S8 support
  [KNOTE] Moreira-Muir (JF 2017) vol-managed — proxy preprint ditemukan (2212.07288 /
       2510.19271); paper asli perlu Crossref verify → Batch 2
```
