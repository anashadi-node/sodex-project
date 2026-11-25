# DIGEST PAPER PRIORITAS — Batch 1 (14 Sep 2026)
**Semua entri = abstract terverifikasi langsung dari arxiv.org/abs/<id>. Label evidence per entri.**

---

## P01 · arXiv 2607.19453 — *Predictive Extrema, Unprofitable Policies: An AI-Assisted Audit of Candle-Based Binance Spot Timing Models*
**Relevansi: █████ CEX-Binance (LANGSUNG)**
```
Setting : Binance Spot, model ML berbasis candle, paper policy setelah biaya diasumsikan
Temuan  :
 - Selektor 10-pair wajib-harian: −6,72% selama 19 siklus @31 bps biaya; 3 menang / 16 kalah
 - Kebijakan local-minimum: −1,79%; local-maximum sell-to-cash: kalah 2,80% dari buy-hold
 - Keunggulan gross mean 11,11 & 12,21 bps — DI BAWAH stress 21 bps
 - Model OHLCV daily: ROC AUC 0,874–0,896 TAPI average precision hanya 0,134/0,116 → −44,30%
   vs buy-and-hold −41,20%
 - Audit forensik: holdout 30-hari sebelumnya CACAT (tanggal memengaruhi arsitektur,
   horizon 4 jam tidak di-purge di batas split, same-close entry, direktori hasil mentah hilang)
Kesimpulan penulis: "event-ranking performance did not establish positive executable policy
 value. Every operational decision remains NO_TRADE."
```
**Implikasi untuk kita:** (a) AUC tinggi ≠ profit — average precision & biaya yang menentukan;
(b) setiap evaluasi kita WAJIB purge/embargo di batas split dan hindari same-close entry;
(c) jalur "ML memprediksi candle" sudah diuji-audit dan gagal di Binance spot.
**Label: CONFIRMED (audit eksternal, protokol ketat) — sebagai PERINGATAN.**

---

## P02 · arXiv 2606.15715 — *Trading in the Sunshine or in the Shade: Market Impact and Adverse Selection on Hyperliquid*
**Relevansi: █████ SoDEX (venue Hyperliquid, eksekusi)**
```
Data   : 4,3 juta metaorder tersembunyi + 465.000 eksekusi TWAP terlihat (address-level)
Model  : prediksi Admati & Pfleiderer (1991) tentang pre-announcement
Temuan :
 - Metaorder tersembunyi: jadwal front-loaded berbentuk U (transient-impact optimal execution)
 - TWAP terlihat: eksekusi hampir uniform
 - TWAP terlihat → biaya eksekusi LEBIH RENDAH + permanent impact lebih kecil
 - Metaorder tersembunyi yang dieksekusi bersamaan arus TWAP searah → biaya permanen LEBIH TINGGI
   (biaya adverse-selection bergeser ke pihak yang tidak mengumumkan)
 - TWAP terlihat MENARIK penyedia likuiditas: displayed depth naik, book miring ke sisi penyerap
```
**Implikasi:** untuk SoDEX/Hyperliquid pada order besar, TWAP terlihat bisa lebih murah
daripada agresi tersembunyi. Ini kontra-intuitif vs kebiasaan "sembunyikan order".
**Label: CONFIRMED (data on-chain address-level, uji teori eksplisit).**

---

## P03 · arXiv 2608.21888 — *Short-horizon mean reversion in cryptocurrency markets: a matched cross-market measurement*
**Relevansi: █████ SoDEX + CEX (horizon pendek, Binance)**
```
Horizon: 15 menit
Temuan :
 - 90% dari 183 pair Binance punya directional reversal signifikan vs hanya 2,7% dari 187
   saham/ETF AS; konsisten setiap tahun-koin sejak 2021
 - Sinyal ada di TANDA, bukan magnitudo: lag-1 autocorrelation ≈ 0 di koin major, tapi
   "bertaruh melawan candle sebelumnya" menangkap sebagian besar efek
 - Reversal terkonsentrasi SETELAH pergerakan yang digerakkan aggressive taker flow;
   menguat seiring intensitas flow. Kedalaman book yang dikonsumsi TIDAK mengkondisikan apa pun
 - Edge gross puncak ≈1,3 bp/trade vs biaya round-trip 5 bp → "large enough to detect,
   too small to clear benchmark spot capture costs"
 - Tahan artifact battery, permutation null exact, holdout beku 6 bulan
   (AUC gap +0,011, 95% CI [+0,008, +0,014])
```
**Implikasi:** mean-reversion kripto itu NYATA dan tahan uji — tapi pada 15 menit, biaya
memakan edge. Pertanyaan riset kita: apakah pada horizon 1–30 jam (milik kita) rasio
edge/biaya lebih baik? Ini hipotesis falsifiable yang bisa diuji di data sendiri.
**Kondisi pemicu yang terbukti: aggressive taker flow (bukan kedalaman book).** → kandidat fitur.
**Label: CONFIRMED (protokol OOS ketat, permutation null).**

---

## P04 · arXiv 2609.05663 — *What LLM Trading Agents Actually Do in Production: A Six-Month, Population-Scale Record from Two Fleets*
**Relevansi: █████ SoDEX (Hyperliquid perps) + CEX (agentic)**
```
Data   : 6 bulan; DX Terminal Pro (3.505 vault, ETH nyata di Base memecoin, 21 hari)
         + DXAP fleet (500–599 agen, trading Hyperliquid PERPS, Jun–Agu 2026)
         ≈7,5 juta invokasi model, ~300K aksi on-chain, 231.638 multi-tool turn, 14.596 fill
Temuan :
 1. LAPISAN OPERASIONAL menentukan perilaku lebih dari teks strategi:
    risk slider menjelaskan leverage (+0,425 per level); agent fixed effects menyerap 60%
    varian; boundary render leaderboard secara kausal mengarahkan seleksi (RD 1,75x di cut top-3)
 2. SIZING BUTA VOLATILITAS: median leverage 5,0x di SETIAP sextile volatilitas;
    satu sel posture-slider (11% book) menyimpan 62% likuidasi
 3. AGEN TIDAK MENANGKAP UPSIDE YANG MEREKA CAPAI:
    43,2% posisi mencapai ≥+300 bps favorable excursion dalam 24 jam,
    TAPI 49,3% di antaranya DITUTUP dengan return negatif.
    Bracket mekanis memulihkan +39,0 bps per posisi.
 4. TIDAK ADA edge direksional di kedua fleet. DXAP tidak profitable, kalah dari benchmark
    retail Hyperliquid (41% vs 50% win rate round-trip)
 - Bertahan terhadap day-clustered inference, permutation null, restatement fee seragam
```
**Implikasi SANGAT KUAT:**
- Temuan #3 = replikasi eksternal dari diagnosis kita (median negatif + mean positif):
  masalahnya **geometri exit**, bukan sinyal. Bracket mekanis = +39 bps/posisi.
- Temuan #1 = "lapisan operasional > teks strategi" → prioritas ke GOVERNOR/platuk, bukan prompt.
- Temuan #2 = sizing buta volatilitas = cacat umum; kita sudah punya governor inverse-vol
  → ini keunggulan struktural yang harus dipertahankan & diverifikasi.
**Label: CONFIRMED (populasi besar, produksi nyata, robust).**

---

## P05 · arXiv 2607.11888 — *Optimal Adaptive Market Making: Theoretical Framework for High-Yield Liquidity Provision in Perpetual Futures*
**Relevansi: ████ SoDEX (perps, zero maker fee, lintas-bursa)**
```
Kontribusi kunci:
 (i) Teorema dekomposisi PnL: spread income | adverse selection loss | inventory carrying cost |
     hedging friction | funding rate exposure
 (ii) HJB utk kontrol spread-inventory-hedging gabungan, CARA utility + verification theorem
 (iii) High-APY Regime Theorems: 5 parameter dimensionless + "Master APY Formula"
 (iv) Ekonomi nol-fee di DEX perp: ambang entry-exit optimal
 (v) Kebijakan hedging lintas-bursa + dinamika funding → "hedge regime trichotomy"
 (vi) Robustness margin utk ketidakpastian parameter
 (vii) Batas probabilitas drawdown eksponensial + identitas universal APY–VaR
 (viii) Distribusi inventory ergodik + estimasi Bayesian adaptif
 (ix) Kelly-optimal leverage dengan batas kebangkrutan
 (x) Alokasi portofolio multi-pair + hasil saturasi diversifikasi
```
**Implikasi:** ini kerangka matematis paling lengkap untuk jalur maker/farming SoDEX
(make fee nol di DEX perp). Dekomposisi PnL (i) = template audit kita. Kelly+ruin (ix) dan
APY-VaR (vii) = alat kontrol risiko langsung.
**Label: CONFIRMED sebagai framework teori (perlu replikasi numerik lokal sebelum dipakai).**

---

## P06 · arXiv 2602.11708 — *AdaptiveTrend: Systematic Trend-Following with Adaptive Portfolio Construction in Crypto*
**Relevansi: █████ CEX-Binance (horizon 6 jam ≈ 1–30 jam kita)**
```
Arsitektur: trend-following frekuensi tinggi interval 6 JAM
            + konstruksi portofolio adaptif BULANAN
            + alokasi long-short asimetris 70/30
Tiga inovasi: (1) trailing stop dinamis dikalibrasi regime volatilitas intra-hari;
              (2) seleksi aset berbasis rolling Sharpe + filter market-cap;
              (3) alokasi asimetris 70/30 dari drift positif kripto
Evaluasi: 150+ pair, 36 bulan OOS (2022–2024)
        : Sharpe tahunan 2,41 | MaxDD −12,7% | Calmar 3,18
        : mengalahkan TSMOM & equal-weight buy-and-hold secara signifikan
Robustness: sensitivitas parameter, model biaya transaksi, dekomposisi kondisional regime
        (bull/bear/sideways)
```
**Implikasi:** ini blueprint yang paling dekat dengan mandat CEX kita (swing jam-an,
portofolio adaptif, alokasi asimetris, trailing stop kalibrasi volatilitas). WARISAN:
- trailing stop dikalibrasi regime volatilitas ← kita belum punya secara eksplisit
- seleksi aset rolling Sharpe ← kandidat
- alokasi asimetris 70/30 ← layak diuji vs 50/50 kita
**Label: PROMISING (backtest OOS 36 bulan, tapi belum ada replikasi independen/live).**

---

## P07 · arXiv 2606.00071 — *Bitcoin Price Prediction: Peer-Reviewed Evidence and Social Media Discourse*
**Relevansi: █████ kalibrasi epistemik SEMUA divisi**
```
Survei literatur peer-reviewed + diskursus X/Twitter:
 - Pada horizon pendek-menengah: TIDAK ADA studi peer-reviewed yang menunjukkan superioritas
   robust atas baseline naif "harga hari ini" lintas beberapa regime pasar
 - Prediktabilitas harian NYATA tapi TIDAK meluas ke horizon jam-an atau bulanan,
   dan mungkin tidak bertahan setelah biaya transaksi
 - stock-to-flow GAGAL uji OOS formal; Metcalfe's Law ditantang sebagai spurious
 - power law BTC belum diuji distribusional formal
Standar metodologis yang diusulkan penulis:
   walk-forward evaluation | multi-regime holdout windows | naive baseline comparison |
   inclusion of zero in hyperparameter grids | Diebold-Mariano significance testing
Penutup: "the field's primary need is not more models but better evaluation"
```
**Implikasi:** ini dasar epistemik untuk menolak jalur "tambah model prediksi".
Setiap klaim prediktif kita harus lolos 5 standar di atas. Kalimat penutup penulis
sejalan dengan doktrin Profit-First kita.
**Label: CONFIRMED (survei literatur sistematis).**

---

## P08 · arXiv 2606.09478 — *Volatility Forecasting and Return Prediction under Market Regimes*
**Relevansi: █████ CEX (regime gate kita)**
```
Setting: CSI 300 high-frequency, 2005–2023. Dua tahap:
  Tahap 1: realized vol via regime-augmented HARQ + Markov-switching GJR-GARCH
  Tahap 2: XGBoost return prediction dgn fitur vol forecast + indikator regime,
           estimasi walk-forward ketat OOS
Temuan :
 - Peramalan vol SADAR-REGIME konsisten mengalahkan baseline HARQ (dukung uji formal)
 - Prediktabilitas RETURN lemah, BERGANTUNG STATE, terkonsentrasi di regime VOLATILITAS RENDAH
 - Strategi prediktif naif GAGAL setelah biaya realistis
 - TAPI implementasi yang dirancang hati-hati (volatility scaling, low-vol gating,
   kalibrasi threshold, kontrol turnover) MEMPERBAIKI kinerja ekonomi defensif
Kesimpulan: nilai praktis bukan dari forecast return kuat, tapi dari MENGUBAH sinyal lemah
   yang bergantung-state menjadi ATURAN ALOKASI yang robust secara ekonomi
```
**Implikasi:** ini validasi langsung untuk arsitektur kita (HMM regime gate) DAN
arahan: gate pada volatilitas rendah, scaling volatilitas, kontrol turnover.
Ini juga menjelaskan kenapa aggregate CEX kita negatif: sinyal dipakai di semua regime,
padahal prediktabilitas terkonsentrasi di low-vol.
**Label: CONFIRMED (walk-forward ketat, uji formal).**

---

## P09 · arXiv 2606.30037 — *Heads, Not Backbones: Output Heads Dominate Architectures on Fat-Tailed Returns*
**Relevansi: ████ CEX (FreqAI LightGBM)**
```
Uji: 4 backbone (TimesNet, DLinear, N-BEATS, iTransformer) × 3 output head
     (point | Gaussian density | Gaussian mixture K=4), S&P500 1871–2023,
     anchored walk-forward
Temuan :
 - Gradient HEAD itu ketat: point→Gaussian = CRPS −1,3%; Gaussian→mixture = −2,4% lagi
 - Ganti BACKBONE = perubahan CRPS <1,5% (axis rata-rata) → head LEBIH menentu
 - Model Confidence Set tidak mengecualikan varian mana pun pada squared error →
   head memisahkan hanya pada metrik DISTRIBUSI (CRPS, pinball, coverage)
 - Nilai tambah mixture head TERBESAR di regime volatilitas TERTINGGI
 - Horizon-dependent: head dominan di horizon pendek; backbone kembali memimpin di h≥6
```
**Implikasi:** untuk horizon pendek kita, mengganti model/backbone (LightGBM → XGBoost → NN)
adalah usaha dengan hasil kecil. Yang bernilai: HEAD OUTPUT — beri model kemampuan
mengeluarkan DISTRIBUSI (kuantil), bukan titik. Ini juga meningkatkan manajemen risiko
di regime volatil. **Rekomendasi konkret: prediksi kuantil/interval, bukan titik.**
**Label: CONFIRMED (walk-forward anchored, Model Confidence Set).**

---

## P10 · arXiv 2609.37963 — *Not All LPs Are Equal: The Active-Passive Gap in AMM Liquidity Provision*
**Relevansi: ███ SoDEX (jika menyentuh LP/AMM)**
```
Framework markout: dekomposisi profitabilitas LP Uniswap jadi komponen aktif & pasif
  - metode LIFO subtraction (match mint-burn jangka pendek, atribusi markout per swap share)
  - benchmark LP infinitesimal (fully passive, selalu in-range)
Hasil: pada pool concentrated-liquidity ada GAP aktif-pasif SISTEMATIS — LP pasif
  underperform ukuran agregat pool. Gap lebih lebar di Ethereum daripada L2 (konsisten dengan
  nilai liquidity provision aktif saat block time & ordering memungkinkan reaksi).
  LP pasif lebih baik di pool fee tinggi.
Kesimpulan: adverse selection di AMM TIDAK terdistribusi merata antar LP.
```
**Label: CONFIRMED (3 versi Uniswap × 3 chain, dua metode independen konsisten arah).**

---

## P11 · arXiv 2608.19389 — *Concentrated Liquidity Provision: a Reinforcement Learning Perspective*
**Relevansi: ███ SoDEX (alokasi likuiditas adaptif)**
```
Formulasi sebagai stochastic impulse control; RL untuk solusi yang interpretable.
Policy yang dipelajari: alokasi likuiditas menurut mispricing, biaya rebalancing,
ketidakpastian, eksposur inventory, preferensi risiko heterogen.
Efek utama: MENEKAN EKOR KIRI distribusi PnL dan menghindari hasil katastrofik
saat ketidakpastian tinggi.
```
**Label: PROMISING (benchmark vs baseline AMM literatur).**

---

## P12 · arXiv 2609.14481 — *Quantifying Observable High-Frequency Swapping on Arbitrum*
**Relevansi: ███ SoDEX (ekosistem DEX/L2)**
```
Konsep baru: High-Frequency Swapping (HFS) = single-hop swap kontinu pada kadens mesin.
Data: 18 bulan full-chain Arbitrum (Jan 2023–Jun 2024)
Temuan: 477 swapper HFS → ~30 juta swap → >$10^11 notional volume
Kasus yang diidentifikasi: stablecoin arbitrage, CEX-DEX execution gaps,
  short-horizon round-trip trading.
Struktur L2 (deterministic sequencing, block sub-detik, gas minim) menekan MEV klasik
  tetapi memunculkan regime perilaku baru ini.
```
**Label: CONFIRMED (18 bulan full-chain, pipeline reproducible).**
