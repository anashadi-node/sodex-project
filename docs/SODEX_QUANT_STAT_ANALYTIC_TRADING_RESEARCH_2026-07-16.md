# SoDEX Quantitative Statistical Analytics Trading System Research

Generated: 2026-07-16 Asia/Jakarta

## Verdict

Belum ada satu sistem terpadu yang layak disebut **Quantitative Statistical Analytics Trading System khusus SoDEX** secara penuh.

Yang sudah ada adalah kumpulan komponen kuantitatif yang kuat tetapi tersebar:

- SoDEX seven-signal TA probability gate: `scripts/sodex_ta_probability_gate.py`
- TA/OOS directional predictor: `anantara/directional_predictor.py`
- probability calibration/Brier/ECE: `anantara/calibration.py`
- statistical validation gates: `anantara/pregain_validation_gates.py`
- Pre-Gain 7-engine signal suite: `anantara/pregain_engines.py`
- SoDEX walk-forward ML research: `scripts/research/backtest_freqai_sodex.py`
- maker fill-probability research: `scripts/research/river_fill_predictor.py`
- champion/challenger model governance: `anantara/model_registry.py`
- SoDEX system map with `technical_probability_gate`: `scripts/sodex_system_map.py`

Kesimpulan ilmiah: project sudah punya bahan untuk membangun sistem tersebut, tetapi belum ada **single canonical SoDEX quant-stat decision engine** yang menyatukan market data, TA signals, microstructure, calibration, OOS validation, fill probability, transaction-cost model, ratio budget, dan model governance ke satu keputusan `TRADE / WAIT / BLOCK`.

## Scientific Basis

Sistem trading kuantitatif yang sehat tidak boleh hanya menjumlahkan indikator teknikal. Minimal harus:

1. Mendefinisikan data contract: timestamp, symbol, source, latency, spread, price, orderbook, volume, funding, OI, trades, fills.
2. Membuat feature store: TA features, volatility, volume, microstructure, event risk, account/risk state.
3. Membuat label causal: forward return, max adverse excursion, maker fill within N seconds, post-trade PnL, ratio impact.
4. Memakai walk-forward / purged validation, bukan shuffle random.
5. Mengukur probability calibration: Brier, expected calibration error, reliability bins.
6. Menghitung transaction cost: fee, spread, slippage, non-fill, adverse selection.
7. Mengoreksi multiple testing / overfit: PBO, Deflated Sharpe, FDR.
8. Menyimpan model governance: champion/challenger, OOS promotion, rollback.
9. Memblokir live ketika data stale, model uncalibrated, expected edge negatif, atau ratio budget gagal.

Riset eksternal utama:

- Bailey, Borwein, Lopez de Prado, Zhu, "The Probability of Backtest Overfitting": holdout biasa tidak cukup untuk strategi investasi; PBO/CSCV dipakai untuk mengukur risiko overfit. URL: https://ssrn.com/abstract=2326253
- Bailey & Lopez de Prado, "The Deflated Sharpe Ratio": Sharpe perlu dikoreksi untuk selection bias, multiple testing, dan non-normal returns. URL: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Easley, Lopez de Prado, O'Hara, "Flow Toxicity and Liquidity in a High Frequency World": maker bisa rugi karena adverse selection; VPIN memakai volume imbalance dan trade intensity untuk flow toxicity. URL: https://ssrn.com/abstract=1695596
- Benjamini & Hochberg, "Controlling the False Discovery Rate": FDR lebih tepat daripada menerima banyak eksperimen trading tanpa koreksi. DOI: https://doi.org/10.1111/j.2517-6161.1995.tb02031.x

## Local Evidence

### 1. SoDEX Seven-Signal Probability Gate

`scripts/sodex_ta_probability_gate.py` sudah membangun gate khusus SoDEX dari `data/sodex_market_scan/history.jsonl`.

Tujuh signal:

- EMA trend/slope
- RSI
- MACD histogram
- Bollinger position/width
- VWAP deviation
- ATR / realized volatility / drift
- orderflow microstructure: 24h change, spread, funding

Gate memblokir live jika:

- data kurang dari 30 pseudo-candles
- data stale
- coverage signal tidak lengkap
- direction mismatch
- probability di bawah 0.80
- estimated ATR/spread adverse loss melebihi ratio budget

Status: bagus sebagai **pre-entry TA probability/risk gate**, tetapi belum cukup sebagai sistem kuantitatif penuh karena probabilitasnya belum dilatih dan dikalibrasi dari outcome SoDEX historis.

### 2. Directional Predictor

`anantara/directional_predictor.py` adalah contoh metodologi yang lebih benar: 9 signal TA, weighting berdasarkan skill historis, OOS test, Brier calibration, dan kontrak eksplisit bahwa akurasi tidak diasumsikan.

Kelemahannya untuk SoDEX:

- memakai Binance klines, bukan SoDEX-native execution/fill data
- tidak memasukkan ratio real harian
- tidak menghitung maker fill probability dan adverse selection SoDEX
- tidak menjadi canonical gate eksekusi SoDEX

### 3. Calibration Core

`anantara/calibration.py` sudah tepat secara prinsip: raw probability tidak bermakna sebelum dikalibrasi empiris. Ada Brier score, ECE, reliability bins, isotonic calibration.

Ini harus menjadi lapisan wajib setelah `sodex_ta_probability_gate.py`.

### 4. Statistical Validation Gates

`anantara/pregain_validation_gates.py` sudah punya inti institusional:

- probabilistic Sharpe
- minimum backtest length
- Benjamini-Hochberg FDR
- alpha spending
- bootstrap Sharpe CI
- CUSUM dan KL-divergence concept drift

Ini perlu dipakai ulang untuk SoDEX model promotion, bukan hanya Pre-Gain.

### 5. Maker Fill Probability

`scripts/research/river_fill_predictor.py` paling penting untuk menaikkan volume tanpa merusak ratio. Volume SoDEX tidak hanya masalah arah market; maker order harus cepat fill dan tidak adverse-selected.

Model ini sudah benar secara causal:

- features dari OBI snapshot sekarang
- label dari future trades setelah snapshot
- target: fill within 7/15/30 seconds

Ini perlu dinaikkan dari research script menjadi production advisory gate.

### 6. System Map

`scripts/sodex_system_map.py` sudah memasukkan `technical_probability_gate` di canonical flow:

`data_collectors -> market_scan -> technical_probability_gate -> autonomous_research -> monitor_eval -> deep_learning_loop -> policy_and_gates -> execution_guard -> operator_approval -> micro_pilot_or_engine -> experience_log_back_to_learning`

Status: arsitektur mulai benar, tetapi belum ada satu `quant_stat_decision_engine.py`.

## Required SoDEX Quant-Stat Architecture

Target canonical engine:

```text
SoDEX collectors
  -> data quality gate
  -> feature store
  -> seven-signal TA model
  -> microstructure/fill-probability model
  -> event/risk/account context
  -> calibrated probability layer
  -> transaction-cost + ratio simulator
  -> OOS/statistical validation gate
  -> decision: TRADE / WAIT / BLOCK
  -> experience log
  -> champion/challenger promotion
```

Required decision schema:

```json
{
  "symbol": "SOL-USD",
  "side": "sell",
  "decision": "WAIT",
  "prob_direction": 0.81,
  "prob_fill_15s": 0.74,
  "expected_edge_usd": 0.0021,
  "expected_adverse_loss_usd": 0.0036,
  "ratio_budget_usd": 0.0047,
  "calibration_brier": 0.21,
  "oos_win_rate": 0.56,
  "sample_n": 420,
  "blockers": []
}
```

## Gaps

1. `sodex_ta_probability_gate.py` probability masih rule-based, belum empirical calibrated probability.
2. SoDEX-native labels belum disatukan: forward return, fill probability, adverse excursion, realized PnL, realized ratio impact.
3. Fill-probability model masih research-only.
4. Transaction-cost simulator belum menggabungkan fee, spread, slippage, non-fill, adverse selection, dan ratio target dalam satu expected value.
5. Existing validation gates belum menjadi promotion gate wajib untuk SoDEX trading model.
6. Belum ada champion/challenger khusus `sodex_quant_stat`.
7. Belum ada laporan rutin yang menyatakan model layak live atau tidak berdasarkan Brier/OOS/FDR/DSR/PBO.

## Recommended Build Plan

Phase 1: read-only unification.

- Create `scripts/sodex_quant_stat_engine.py`.
- Input: `data/sodex_market_scan/history.jsonl`, OBI/trades data, `data/sodex_monitor_eval/latest.json`, micro pilot history.
- Output: `data/sodex_quant_stat/latest.json` and JSONL history.
- No orders, no cancels.

Phase 2: empirical labeling.

- Build labels per symbol/time:
  - future return over 1m/5m/15m
  - max adverse excursion
  - maker bid/ask fill within 7/15/30s
  - realized round-trip PnL where available
  - realized volume/loss ratio

Phase 3: calibration and validation.

- Apply `anantara/calibration.py`.
- Apply `anantara/pregain_validation_gates.py` logic to SoDEX experiments.
- Store Brier, ECE, OOS hit-rate, sample size, drift, and multiple-testing adjusted acceptance.

Phase 4: gate integration.

- `sodex_micro_pilot.py` should consume quant-stat output in addition to current TA gate.
- Live block unless:
  - data fresh
  - probability calibrated
  - OOS sample sufficient
  - expected edge positive after cost
  - expected adverse loss within ratio budget
  - fill probability above threshold
  - no safety halt

## Bottom Line

Jawaban langsung: **belum sepenuhnya dibuat**.

Yang sudah dibuat adalah **SoDEX technical probability gate** yang mengolah 7 signal sebelum live micro-pilot. Itu langkah benar, tetapi masih level gate. Sistem kuantitatif statistik yang sesungguhnya harus menjadi engine terpisah yang menggabungkan signal TA, market microstructure, fill probability, calibration, OOS validation, transaction cost, ratio budget, dan champion/challenger governance.

Perbaikan signifikan berikutnya bukan menaikkan notional dulu, tetapi membangun `sodex_quant_stat_engine.py` read-only supaya keputusan volume tidak lagi bergantung pada signal mentah atau asumsi probability yang belum dikalibrasi.
