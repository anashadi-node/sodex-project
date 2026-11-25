# DIGEST PAPER PRIORITAS — Batch 2 (P13–P24)
**Abstract terverifikasi langsung dari arxiv.org/abs/<id>, 14 Sep 2026.**

---

## P13 · arXiv 2607.09426 — *The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures*
**Relevansi: █████ CEX-Binance (LANGSUNG) + SoDEX**
```
Data   : 6 kontrak perpetual Binance, data trade
Temuan :
 - Ledakan periodik volatilitas & volume pada tanda 1-menit, 5-menit, dan QUARTER-HOUR
 - "Trade-size roundness" menurun tajam saat ledakan → indikasi partisipasi algoritmik
 - "Autocorrelation Map" (clock-phase-resolved) mengungkap dependensi serial order flow &
   return pada pembukaan quarter-hour yang TIDAK terlihat oleh ukuran konvensional
 - Return pembukaan PREDIKTABEL out-of-sample
 - ORDER IMBALANCE pembukaan memprediksi return 4 SAMPAI 12 JAM ke depan
   (efek jauh lebih lemah pada frekuensi clock-time yang lebih halus)
```
**Implikasi:** ini temuan ber-horizon 4–12 jam — PERSIS rentang swing 1–30 jam kita.
Kandidat fitur kuat & spesifik: `clock_phase` (menit-dalam-jam), `opening_order_imbalance`,
`trade_size_roundness`. Perlu diuji di data 1h kita (proxy) atau 15m.
**Label: CONFIRMED (OOS predictable, 6 kontrak Binance).**

---

## P14 · arXiv 2607.09230 — *When Does Order Flow Matter? State-Dependent L2 Liquidity-State Transitions in Crypto Futures*
**Relevansi: █████ CEX + SoDEX (desain sinyal OBI/OFI kita)**
```
Data   : Binance BTCUSDT & ETHUSDT futures 2023–2026, top-20 L2 order book + trade flow
         + window event makro
Desain : supervised discrete L2 liquidity-state transition task
         rolling monthly OOS folds, event-clustered validation, blocked permutation tests
         tiap layer fitur hanya diterima bila memperbaiki layer di bawahnya (panel sama)
Temuan :
 - Sinyal prediktif ORDER PERTAMA = PRE-EVENT L2 LIQUIDITY STATE (state kasar menang kuat)
 - Model logit atas fitur L2 kontinu GAGAL memperbaiki baseline state tsb
 - Model L2 nonlinier dangkal menambah gain robust sebesar baseline itu sendiri
 - ORDER FLOW menambah nilai HANYA bila dilapiskan di atas model L2 state —
   BUKAN sebagai pengganti
 - Nilai ini TIDAK robust lintas-simbol
```
**Implikasi:** sangat operasional untuk kita. Sinyal kita saat ini berbasis OBI/OFI.
Bukti ini mengatakan: (a) state likuiditas L2 adalah prediktor tingkat-pertama;
(b) OFI hanya berguna DI ATAS state; (c) jangan berharap portabilitas lintas-simbol.
→ Urutan arsitektur: `L2 state → (opsional) OFI → sinyal`, bukan `OFI → sinyal`.
**Label: CONFIRMED (rolling OOS bulanan + blocked permutation).**

---

## P15 · arXiv 2603.09164 — *Slippage-at-Risk (SaR): Forward-Looking Liquidity Risk Framework for Perpetual Futures Exchanges*
**Relevansi: █████ SoDEX (venue perp, risiko likuidasi)**
```
Kontribusi: 3 metrik dari mikro-struktur order book SAAT INI (bukan historis):
  SaR(α)  = kuantil slippage lintas-seksi
  ESaR(α) = expected slippage di ekor distribusi
  TSaR(α) = tail slippage agregat dalam USD
Ekstensi: "concentration adjustment" — menghukum struktur likuiditas rapuh
  saat sedikit market maker mendominasi penyediaan kuotasi
Pemetaan langsung SaR → kebutuhan modal optimal (mengacu Chitra et al. 2025)
Empiris: order book HYPERLIQUID, termasuk likuidasi kaskade 10 Okt 2025
Validitas: SaR terbukti sebagai LEADING INDICATOR stres sistemik
```
**Implikasi:** kerangka risiko eksekusi yang forward-looking — kita hanya punya metrik
spread/depth backward. Untuk SoDEX: hitung SaR/ESaR/TSaR + penalti konsentrasi sebelum
menentukan ukuran posisi & buffer likuidasi.
**Label: CONFIRMED (data Hyperliquid in-sample, kaskade nyata).**

---

## P16 · arXiv 2609.04917 — *Artificial Intelligence in Equity and Crypto Markets: Progress, Profitability Evidence, and the Limits of Automated Investing*
**Relevansi: █████ kalibrasi epistemik SELURUH riset ini**
```
Critical state-of-the-art review s.d. 31 Agustus 2026:
  cakupan = ekuitas listed, ETF, crypto CEX spot, PERPETUAL FUTURES, pasar on-chain
Kerangka: "alpha-translation chain" —
  informasi point-in-time → sinyal stabil → posisi feasible → order executable →
  return risk-adjusted setelah biaya
Temuan : kemajuan NYATA tapi terutama UPSTREAM (prediksi, pemrosesan teks, desain
  portofolio, integrasi workflow). Bukti untuk kinerja NET yang tahan lama LEBIH TIPIS.
  Perusak translasi ke net alpha: kontaminasi temporal, seleksi berulang, survivorship,
  benchmark lemah, biaya implementasi, mekanika venue, kapasitas.
  Hasil historis kuat BERDAMPINGAN dengan predictor decay, kegagalan look-ahead yang
  dikoreksi, bukti prospektif campur, dan SANGAT SEDIKIT catatan modal live yang diaudit.
  Kripto butuh perlakuan terpisah untuk spot, perpetual, dan DEX (cash flow & eksekusi).
```
**Implikasi:** dokumen ini adalah *ground truth epistemik* untuk seluruh komisi riset ini.
Setiap rekomendasi kita harus lolos rantai translasi alpha, bukan berhenti di "sinyal".
**Label: CONFIRMED (review kritis independen, horizon s.d. Agu 2026).**

---

## P17 · arXiv 2602.00776 — *Explainable Patterns in Cryptocurrency Microstructure*
**Relevansi: █████ CEX + SoDEX (fitur mikro-struktur)**
```
Data   : order book + trade Binance Futures perpetual, frekuensi 1 DETIK,
         1 Jan 2022 – 12 Okt 2025; aset: BTC, LTC, ETC, ENJ, ROSE
         (rentang market cap satu orde besaran)
Metode : pipeline CatBoost terpadu + objective GMADL direction-aware + time-series CV
Temuan :
 - Peringkat fitur & bentuk dependensi SHAP STABIL lintas aset meski likuiditas &
   volatilitas heterogen
 - Fitur terhubung ke teori mikro-struktur: order flow imbalance, spread, adverse selection
 - Tradability divalidasi: taker top-of-book backtest konservatif + maker fixed-depth backtest
 - Analisis khusus flash crash: performa berbeda strategi taker vs maker memvalidasi
   teori adverse selection & menyorot risiko sistemik algorithmic trading
 - → representasi mikro-struktur yang PORTABEL lintas aset; motivasi "universal feature library"
```
**Implikasi:** mendukung pendekatan "satu perpustakaan fitur lintas-aset" — bertentangan
sedikit dengan P14 (yang bilang nilai OFI tidak portabel lintas-simbol). Bedanya: P17
soal STABILITAS PERINGKAT fitur; P14 soal NILAI TAMBAH prediktif. Keduanya bisa benar.
**Label: CONFIRMED (1 detik, 4 tahun, 5 aset, backtest taker & maker).**

---

## P18 · arXiv 1701.03960 — *Optimal Trading with a Trailing Stop*
**Relevansi: ████ SoDEX/CEX (mekanika trailing stop)**
```
Masalah: timing beli lalu jual dengan trailing stop (drawdown persentase tertentu)
Framework: linear diffusion umum; optimal DOUBLE STOPPING problem dengan maturity
           bergantung-lintasan (path-dependent) acak
Hasil  : (1) strategi likuidasi optimal SEBELUM trailing stop ditrigger, dengan bukti
             bahwa SELL LIMIT ORDER + trailing stop adalah optimal bersama;
         (2) hasil analitik dipakai menyelesaikan strategi akuisisi aset optimal
             sekaligus menginisiasi trailing stop;
         (3) metode solusinya menghasilkan metode numerik efisien untuk menghitung
             region akuisisi & likuidasi optimal.
Contoh: model exponential Ornstein-Uhlenbeck + analisis sensitivitas.
```
**Implikasi:** dasar matematis bahwa trailing stop + sell-limit adalah kombinasi OPTIMAL
(dukung desain exit berlapis). Membenarkan riset exit-geometry sebagai jalur utama.
**Label: CONFIRMED (teori, dengan bukti optimalitas).**

---

## P19 · arXiv 2109.10662 — *Evaluation of Dynamic Cointegration-Based Pairs Trading Strategy in the Cryptocurrency Market*
**Relevansi: ████ CEX (kandidat metode market-neutral)**
```
Metode: pairs trading kointergrasi dinamis + framework look-back window optimal
        Uji: Engle-Granger, Kapetanios-Snell-Shin (KSS), Johansen
        Kalibrasi kecepatan mean-reversion proses Ornstein-Uhlenbeck → half-life
        untuk SELEKSI ASET dan ESTIMASI look-back window
Data   : data minute-binned untuk pembentukan sinyal; backtest di bursa Bitmex
Temuan :
 - Mengalahkan pendekatan naif buy-and-hold
 - Koleksi koin yang BANYAK untuk membentuk spread MEMPERBAIKI profitabilitas risk-adjusted
 - Maximum drawdown relatif rendah → layak deploy
 - Ada kelas koin yang punya peluang arbitrase lebih baik daripada yang lain
 - Mempertimbangkan batasan mikro-struktur pasar
```
**Implikasi:** jalur market-neutral yang tidak bergantung prediksi arah — sangat relevan
untuk CEX (mengurangi beta) dan untuk mencapai target tanpa risiko direksional penuh.
**Label: CONFIRMED (backtest Bitmex, metode standar ekonometri).**

---

## P20 · arXiv 2607.27070 — *Where Does the Criticality Live? Early-Warning Signals are Event-Heterogeneous Across Seven Crypto-Perpetual Liquidation Cascades*
**Relevansi: ████ SoDEX/CEX (disiplin alarm risiko) — INI PERINGATAN PENTING**
```
Data : 7 kaskade likuidasi BTC besar (2022–2025), termasuk rekor $19B (10 Okt 2025)
       harga menit + data leverage/order-flow 5 menit
Uji  : residu detrended → rolling variance & lag-1 autocorrelation → tren pra-kaskade
       via Kendall-tau, menyapu 39 konfigurasi analisis per variabel per event
Temuan:
 - TIDAK ADA variabel yang event-invariant
 - Harga membawa tanda critical-slowing-down di 5 dari 7 event, TAPI BISU di tepat
   2 kejutan berita mendadak (tarif) → struktur DUA-TIPE: endogen (akumulasi) vs eksogen (shock)
 - Event Okt 2025 (yang in-sample tampak bertanda leverage) = OUTLIER, bukan aturan
 - Satu keteraturan yang bertahan di semua event BERDATA: KOMPRESI VARIAN TAKER ORDER-FLOW,
   lolos placebo 300-onset (Fisher-combined p ≈ 5e-6) — TAPI ini prekursor level-POPULASI,
   BUKAN alarm per-event
Kesimpulan penulis: klaim critical-slowing-down berbasis satu event di crypto derivatif
  "fragile by construction"
```
**Implikasi SANGAT PENTING:** jangan bangun sistem alarm risiko berdasarkan pola satu
krisis. Prekursor yang tahan uji = kompresi varian taker order-flow (fitur yang bisa kita
hitung dari data trade). Gunakan sebagai skor risiko populasi, bukan alarm tunggal.
**Label: CONFIRMED (7 event, 39 konfigurasi, placebo 300-onset).**

---

## P21 · arXiv 2412.18405 — *Generalized Mean Absolute Directional Loss (GMADL) for ML Trading Models*
**Relevansi: █████ CEX (FreqAI LightGBM — langsung bisa dipakai)**
```
Klaim: loss function khusus untuk model ML di trading. Terlepas dari kelas aset &
       kompleksitas model, GMADL menghasilkan hasil SUPERIOR dan properti numerik lebih
       baik saat optimisasi dibanding loss regresi & klasifikasi klasik.
Mekanisme: menyelaraskan TUJUAN PEMBELAJARAN dengan KINERJA TRADING, bukan
       minimisasi error generik atau akurasi direksional sederhana.
       Parametrisasi tambahan → fleksibilitas sensitivitas terhadap magnitudo return
       yang berbeda, memengaruhi konsistensi evaluasi lintas regime.
Praktik: hyperparameter tuning, architecture testing, walk-forward optimization;
       data dunia nyata dari berbagai kelas aset.
```
**Implikasi:** kita memakai LightGBMRegressor dengan loss regresi standar (MSE).
P21 + P17 (yang memakai GMADL) menunjukkan bahwa MENGGANTI LOSS adalah intervensi
berdaya tinggi dengan biaya rendah — sejalan dengan P09 (head/loss > backbone).
**Label: CONFIRMED (klaim penulis, walk-forward; perlu replikasi lokal).**

---

## P22 · arXiv 2606.29347 — *Adaptive Financial Transformer with Regime-Gated Attention*
**Relevansi: ███ CEX (ide regime-gating; bukan untuk adopsi langsung)**
```
Kontribusi: Market Regime Encoder + Adaptive Gate Network + Adaptive Financial Context
  → membiaskan self-attention berdasarkan regime laten; 95 fitur → 11 kategori semantik
PENTING: studi ini "identifies and corrects sequence alignment and backtesting issues
  that can inflate reported trading performance"
Objective komposit sadar-finansial: error prediksi + akurasi direksional + Sharpe non-overlapping
Hasil: performa kompetitif, kompleksitas −15,2%, efisiensi parameter lebih baik
```
**Implikasi:** yang paling berharga bukan arsitekturnya, melainkan pengakuan bahwa
"sequence alignment & backtesting issues" menggelembungkan performa — sejalan P01 & P16.
**Label: PROMISING (evaluasi kronologis, 5 seed, ablation); ide regime-gating = valid.**

---

## P23 · arXiv 2608.23808 — *Equity Strategy Backtesting: Luck or Edge? The MinervaScore*
**Relevansi: █████ SEMUA (standar audit backtest kita)**
```
Masalah: backtest dipilih setelah banyak percobaan parameter → hasil historis kuat bisa
  mencerminkan keberuntungan pencarian, bukan sinyal.
MinervaScore = gabungan 4 kuantitas validasi mapan:
  Deflated Sharpe Ratio + Probability of Backtest Overfitting +
  Superior Predictive Ability + Minimum Track Record Length
  + diagnostik stabilitas regime → margin bertanda → skor 0–100
  "Robustness Seal" biner: skor ≥80 hanya bila kelima gate lolos
Kalibrasi: 359.062 catatan backtest produksi
Hasil sintetik: AUROC 0,989 memisahkan sinyal sejati dari keberuntungan backtest
UJI PRA-REGISTRASI pada data pasar nyata yang belum dilihat:
  TIDAK ada hubungan forward signifikan (Spearman rho = 0,013, permutation p = 0,40)
Kesimpulan penulis: ini lapisan VALIDASI & PELAPORAN yang dapat diaudit,
  BUKAN bukti prediktabilitas pasar nyata.
```
**Implikasi KRITIS:** skor robustness yang bagus TIDAK menjamin profit ke depan.
Gunakan DSR/PBO/SPA/MinTRL sebagai GATE KELAYAKAN (mencegah sampah masuk), bukan
sebagai prediktor. Ini menutup pintu "kita punya skor bagus, berarti pasti profit".
**Label: CONFIRMED (kalibrasi 359K backtest + uji pra-registrasi negatif).**

---

## P24 · arXiv 2209.05559 — *Deep RL for Cryptocurrency Trading: Practical Approach to Address Backtest Overfitting*
**Relevansi: ████ CEX/SoDEX (disiplin anti-overfit)**
```
Pendekatan: (1) formulasikan deteksi backtest overfitting sebagai UJI HIPOTESIS;
            (2) latih agen DRL, estimasi PROBABILITAS OVERFITTING, TOLAK agen yang overfit;
            (3) uji pada 10 cryptocurrency, 01/05–27/06/2022 (pasar crash dua kali):
                agen yang lebih sedikit overfit memberi return LEBIH TINGGI daripada
                agen yang lebih overfit, strategi equal-weight, dan indeks S&P DBM
Kesimpulan: menolak agen overfit meningkatkan peluang kinerja baik → layak deploy.
```
**Implikasi:** prosedur operasional: setiap kandidat model/parameter → estimasi PBO →
tolak di atas ambang. Ini melengkapi P23 (gate sebelum, bukan sesudah).
**Label: CONFIRMED (uji pada periode crash nyata).**
