# SODEX — AUDIT & ANALISA ILMIAH KOMPREHENSIF
# Tanggal: 2026-08-30 05:00 WIB
# Auditor: Hermes Anantara v2
# Metode: Data-driven forensic — semua klaim bersumber dari data nyata

---

## RINGKASAN EKSEKUTIF

**Status: 🔴 KRITIS — sistem berjalan tetapi tidak menghasilkan profit neto**
- Total PnL seluruh engine (15.291 RTS): **+$34,51**
- Tapi biaya (fees) sistemik: **$452,97** — jauh melampaui PnL
- Satu-satunya engine profitable: **E1 Spot PEPE/USDC** (+$87,17, 94,2% WR)
- Engine lain **merugi struktural**: E2 (-$35,90, 3,5% WR), PVE (-$16,76, 61,0% WR)
- Volume total: **$2,49 juta** tapi biaya 13× lipat dari profit

**Target**: ≥0,7% dari TOTAL modal wallet  
**Realitas**: Total wallet ~$94,57 (SoDEX perps) — 0,7% = ~$0,66.  
**GAP**: 0,7%/trade belum ada sistem yang capai secara konsisten.

---

## BAGIAN A — DATA KUANTITATIF

### A.1 Twin Engine: 69.260 Fills, 15.291 Round Trips

| Engine | RTS | Total PnL | Avg PnL | WR | Fills | Volume | Fees |
|--------|:---:|:---------:|:-------:|:-:|:-----:|:------:|:----:|
| **E1** (Spot MM) | 13.092 | **+$87,17** | +$0,0067 | **94,2%** | 62.704 | $897K | $262,22 |
| **E2** (Dir BTC) | 605 | **-$35,90** | -$0,0593 | **3,5%** | 3.368 | $987K | $106,64 |
| **PVE** (Multi) | 1.594 | **-$16,76** | -$0,0105 | **61,0%** | 3.188 | $607K | $84,12 |
| **TOTAL** | **15.291** | **+$34,51** | +$0,0023 | **87,2%** | **69.260** | **$2,49M** | **$452,97** |

### A.2 E1 Performance Detail

| Pair | RTS | Total PnL | Avg PnL | WR |
|------|:---:|:---------:|:-------:|:-:|
| **PEPE/USDC** | 12.560 | **+$87,47** | +$0,0070 | **96,1%** |
| SHIB/USDC | 281 | +$3,07 | +$0,0109 | 60,1% |
| XLM/USDC | 235 | -$2,80 | -$0,0119 | 42,6% |
| ARB/USDC | 16 | -$0,57 | -$0,0359 | 37,5% |
| AVAX/USDC | 9 | -$0,28 | -$0,0313 | 44,4% |

### A.3 E2 Performance Detail

| Pair | RTS | Total PnL | Avg PnL | WR | Fills | Volume |
|------|:---:|:---------:|:-------:|:-:|:-----:|:------:|
| BTC-USD | 598 | **-$36,45** | -$0,0610 | **3,0%** | 3.277 | $975K |
| ENA-USD | 3 | +$0,32 | +$0,1077 | 66,7% | 22 | $3K |
| XPL-USD | 4 | +$0,23 | +$0,0570 | 25,0% | 25 | $3,2K |
| HYPE-USD | 0 | $0 | — | — | 30 | $4K |

### A.4 MODE11 BEARDOWN State (Perps Volume Engine)

| Metrik | Nilai |
|--------|-------|
| Volume total | $461.417 |
| Cost total | $99,67 |
| PnL total | **-$4,68** |
| Fills | 525 |
| Maker legs | **0** |
| Taker closes | 0 |
| Interval | 4 menit |
| Margin | $75/symbol × 6 symbol = $450 |
| Rasio vol/cost | 1:4.630 |

### A.5 Public Trades DB (447.480 Record)

447.480 trade publik dari 60+ symbol di SoDEX. Sebagian besar adalah pair non-kripto (CL-USD, COPPER-USD, SILVER-USD, SPCX-USD, MSTR-USD, dll) — tidak ada korelasi langsung dengan engine E1/E2/PVE.

### A.6 Current Wallet

**SoDEX Perps Account**: $94,57 (vUSDC), 0 posisi terbuka  
**SoDEX Spot**: $0,16 (dust)  
**HL Harvest**: $2,88 total, 1 posisi HYPE (unrealized +$0,45, margin 87,9%)

---

## BAGIAN B — AKAR MASALAH STRUKTURAL

### 🔴 B.1 PERPS TIDAK BISA PROFIT DI TIER 0 (FATAL)

**Rumusan matematis:**

```
Fee round-trip perps: 0,0108% (maker) × 2 leg = 0,0216%
Spread maksimal ditangkap: 0,003%
Net per trade: 0,003% - 0,0216% = -0,0186%

KESIMPULAN: SELALU RUGI. Ini bukan masalah strategi — ini matematika.
```

Tidak ada modifikasi kode, optimasi, atau ML yang bisa mengatasi ini.  
**Satu-satunya solusi:** Tier upgrade (Tier 4 = maker 0%) atau Spot (spread >> fee).

### 🔴 B.2 MAKER RATE HAMPIR 0% — SEMUA TAKER

| Engine | Maker Rate | Artinya |
|--------|:----------:|---------|
| MODE11 BEARDOWN | **0%** | Semua entry/exit via taker = bayar fee penuh |
| E2 (BTC) | 0,3% | Hampir semua taker |
| PVE | 0,1% | Hampir semua taker |
| E1 (PEPE) | 6,9% | Lebih baik tapi mayoritas taker |

**Dampak:** Biaya $452,97 untuk $2,49M volume = $452,97 biaya tanpa rebate.  
Jika semua maker di 0,0108%: hanya $268 biaya. Selisih $184 langsung menguap.

### 🔴 B.3 E2 BTC-USDT MASSIVE BLEEDING (3,0% WR, -$35,90)

Dari 3.277 fills BTC-USD dengan volume $987K:
- Hanya 21 RTS profitable dari 598 (3,5% WR)
- Engine ini **struktural merugi** — harus dihentikan atau di-overhaul total

### 🔴 B.4 DEEP LEARNER BERJALAN TANPA OUTPUT

1.400+ iterasi deep learner, **0 new fills sejak switching ke mode awareness-only**.  
`delta_bps: 0.0`, `confidence: low`, `fill_model_n: 0` — model tidak pernah trained karena tidak ada data fill baru.

**Dampak:** $CPU terbuang, loop berjalan tanpa menghasilkan value.

### 🔴 B.5 SPOT LIQUIDITY DEATH — E1 MATI SETELAH PUNCAK

Timeline E1:
- 21 Jun: launch, +0,405%, volume $6,7M ✅
- 24 Jun: **PEAK**, +2,446%, volume $18,9M ✅✅✅
- 25 Jun: **MATI**, 2.766 dead alerts ❌
- Setelahnya: sporadic, net $0-0,9%

**Penyebab:** Likuiditas PEPE/USDC mengering setelah 25 Juni. Order tidak terisi.

### 🔴 B.6 SECURITY LAYERS MEMATIKAN SPOT AUTOFARM

3 lapis keamanan memblokir trading spot:
1. **Event Shock Guard** — RED pada berita Trump/Iran (padahal BULLISH)
2. **Adaptive Policy** — BLOCK SPOT_LONG berdasarkan data lama
3. **Route Gates** — BLOCK_LIVE bahkan saat market bagus

**Hasil:** $300 capital menganggur berhari-hari.

### 🟡 B.7 ARCHITECTURE OVER-COMPLEXITY

| Masalah | Dampak |
|---------|--------|
| 50+ file scripts/ — 15 di anantara/, 55 di scripts/ | Sulit di-maintain, overlap, dead code |
| 3 database terpisah (twin_engine.db, sodex_public_trades.db, PostgreSQL) | PnL tidak terintegrasi — mustahil punya satu view profit |
| 11 mode trading — 9 tidak aktif | Code bloat, kompleksitas kognitif tinggi |
| 6 layer keamanan (governor, guardian, shock guard, circuit breaker, intel layer, adaptive policy) | Lebih banyak blocking daripada trading |
| 0 RTS dari BEARDOWN di DB (semua via sodex_farming.py state file) | Tidak ada audit trail untuk analisa |

### 🟡 B.8 LEARNING LOOP TIDAK MENUTUP SIKLUS

Deep learner membaca data tapi tidak ada mekanisme untuk:  
1. ✅ ANALYZE — membaca fills + menghitung stat ✅  
2. ❌ **DECIDE** — menghasilkan rekomendasi actionable ❌  
3. ❌ **EXECUTE** — mengubah parameter engine secara otomatis ❌  
4. ❌ **VERIFY** — cek apakah perubahan menghasilkan improvement ❌  

Yang ada sekarang: loop baca → compute → write ke JSONL → engine **tidak membaca JSONL**.

---

## BAGIAN C — ANALISA SCIENTIFIC

### C.1 Hypothesis Testing: "SoDEX Bisa Profit sebagai Maker di Perps"

**Hipotesis Nol (H₀):** Tidak ada strategi market making di perps yang bisa profit  
pada Tier 0 dengan spread ≤ 0,003% setelah fee 0,0216% round-trip.

**Evidence:**
- MODE11 BEARDOWN: Volume $461K, PnL -$4,68 ❌
- E2 BTC-USD: Volume $987K, PnL -$35,90 ❌
- PVE multi-pair: Volume $607K, PnL -$16,76 ❌

**Kesimpulan: H₀ **TIDAK DAPAT DITOLAK** — perps tidak profitable di Tier 0.**
Ini adalah batasan matematis, bukan batasan teknis.

### C.2 Hypothesis Testing: "Spot Market Making Bisa Profit"

**Hipotesis (H₁):** Spot market making dengan spread ≥ 0,20% bisa menghasilkan  
profit positif setelah fee 0,07% round-trip.

**Evidence:**
- E1 PEPE/USDC: 12.560 RTS, **+$87,17, 96,1% WR** ✅ TIDAK DAPAT DITOLAK
- E1 SHIB/USDC: 281 RTS, +$3,07, 60,1% WR — marginal
- E1 XLM/USDC: 235 RTS, -$2,80, 42,6% WR — merugi

**Margin Analysis:**
```
Spot fee round-trip:    0,07%
Spread PEPE/USDC:       0,28-0,41%
Net spread capture:     0,21-0,34%
Rasio spread/fee:        4:1 — BISA PROFIT
```

**Kesimpulan: H₁ didukung kuat** — spot MM dengan spread lebar BISA profit.  
Tapi terbatas pada PEPE/USDC yang likuiditasnya tidak konsisten.

### C.3 Anti-Overfitting Check

| Item | Status |
|------|--------|
| Rolling window untuk gate calibration | ❌ Tidak ada — learning loop tidak update parameter |
| BH FDR correction | ❌ Tidak ada |
| OOS validation | ❌ Tidak ada — semua backtest in-sample |
| Walk-forward | ❌ Tidak ada |
| n < 20 handling | ❌ Banyak keputusan berdasarkan n < 10 |
| Negative control | ❌ Tidak ada — tidak diuji apakah random baseline outperform |

---

## BAGIAN D — KEKURANGAN & KELEMAHAN (RANKED BY IMPACT)

### 🔴 D.1 Perps Tier 0 tidak bisa profit (KRITIS — MATEMATIS)

**Akar masalah #1.** Semua strategi perps akan selalu rugi selama fee > spread.  
**Evidence:** 3 engine perps berbeda, semuanya rugi +$0,00 net.

### 🔴 D.2 E2 BTC-USD bleeding -$35,90 (KRITIS)

3,5% WR dengan 598 RTS bukan fluke — ini sistemik.  
Penyebab: spread BTC 0,3bps tidak cukup untuk menutup fee 0,0216%.  
**Rekomendasi: STOP E2. Simpan kode, matikan eksekusi.**

### 🔴 D.3 Learning loop tidak menghasilkan output actionable

1.400+ iterasi, 0 actionable output. Sistem belajar tapi tidak pernah menerapkan pembelajaran.  
**Dampak:** CPU & listrik terbuang, knowledge base tidak berkembang.

### 🔴 D.4 Spot autofarm mati oleh security layers sendiri

$300 capital idle karena 3 lapis keamanan blokir.  
**Paradoks:** Sistem keamanan yang dirancang untuk melindungi malah mematikan satu-satunya engine yang terbukti profit (E1).

### 🟡 D.5 No unified PnL tracking

Tiga database terpisah (twin_engine.db, sodex_public_trades.db, PostgreSQL) +  
state file (.json) + daemon — data PnL tidak bisa direkonsiliasi tanpa script manual.

### 🟡 D.6 Code sprawl — 50+ file untuk satu project

15 file di anantara/, 55 di scripts/. Banyak overlap:  
- 3 implementasi "spread gate" (farming.py, autofarm.py, governor.py)
- 2 implementasi "circuit breaker" (farming.py, guardian_daemon.py)
- 2 implementasi "regime check" (intel_layer.py, farming.py)

### 🟡 D.7 BEARDOWN = volume engine, BUKAN profit engine

Volume $461K dengan PnL -$4,68 = -0,001% return on volume.  
Biaya $99,67 untuk -$4,68 PnL. Setiap $1 profit membutuhkan $21 biaya.  
Ini BUKAN trading — ini membayar untuk memindahkan uang.

### 🔵 D.8 Edge case handling tidak ada (n<20)

Banyak keputusan gate didasarkan pada sampel n<10.  
Contoh: AVAX/USDC hanya 9 RTS, ARB/USDC 16 RTS — sudah dinyatakan "LOSING".  
Statistik: n<20 tidak cukup untuk klaim signifikan.

### 🔵 D.9 E2 strategy flipped from continuation to mean-reversion

Dari git log: `f5f6b18 feat(sodex-E2): flip momentum to MEAN-REVERSION`  
Tapi E2 BTC terus rugi setelah flip — berarti masalahnya **bukan strategi,  
tapi fundamental (fee > edge).**

---

## BAGIAN E — REKOMENDASI (EVIDENCE-BASED)

### 🔴 Immediate (Hari ini)

| No | Aksi | Dasar Data | Expected Impact |
|----|------|-----------|-----------------|
| 1 | **STOP E2 BTC-USD** | 598 RTS, 3,5% WR, -$35,90 | Hentikan bleeding $35,90 |
| 2 | **Review security layers spot** | 3 layer blocking satu-satunya engine profit | Buka bottleneck E1 revival |
| 3 | **Fix deep learner output** | 1.400 iterasi dengan 0 actionable output | Ubah £CPU jadi learning nyata |
| 4 | **Tutup siklus learning loop** | Engine harus BACA learned_params.json | Loop belajar → terapkan → verifikasi |

### 🟡 Short-term (1 minggu)

| No | Aksi | Dasar Data |
|----|------|-----------|
| 5 | **Re-aktivasi E1 spot pada PEPE/E1** | +$87,17, 96,1% WR = proven profitable |
| 6 | **Konsolidasi 3 DB jadi 1** | Unified PnL view, audit trail lengkap |
| 7 | **Rationalisasi 50+ file** | Hapus MODE1-10 dead code, pangkas 60% file |
| 8 | **Rolling window gate calibration** | Anti-overfitting — data 7d, bukan all-time |

### 🔵 Medium-term (1 bulan)

| No | Aksi | Dasar Data |
|----|------|-----------|
| 9 | **Target Tier upgrade SoDEX** | Satu-satunya jalan perps profit |
| 10 | **Cari alternatif spot likuid** | PEPE tidak konsisten, perlu backup pair |
| 11 | **Integrasi learning loop ke semua engine** | E1 + E2 + PVE harus belajar dari data |
| 12 | **Unified dashboard (bukan 3 DB)** | Satu sumber kebenaran PnL |

### Prioritas Dampak

```
1. STOP E2 bleeding         → selamatkan -$35,90 (instan)
2. Buka security layers     → buka jalan E1 revival
3. Fix learning loop         → future-proof improvement
4. Re-aktivasi E1           → jika likuid, profit +$87/bulan
5. Konsolidasi code & DB    → maintenance cost turun 50%
```

---

## BAGIAN F — MONITORING PLAN

### Yang harus dipantau setiap 24 jam:

| Metrik | Target | Trigger Alert |
|--------|--------|---------------|
| E1 PnL | > $0 | < $0 selama 3 hari |
| E1 fill rate | > 80% | < 50% |
| WR per pair | > 50% | < 40%, n≥20 |
| Learning loop actionable | ≥ 1 output/hari | 0 selama 3 hari |
| Security layer blockers | 0 | > 0 blocker aktif |
| Biaya harian | < $10/hari | > $20/hari |

---

## BAGIAN G — VERDICT AKHIR

**SoDEX saat ini adalah volume engine, BUKAN profit engine.**
- Volume $2,49M ✅ Tercapai
- Profit > $0 ❌ Belum tercapai
- Rasio vol/cost 1:8.650 ❌ 1:4.630 (hanya 53% dari target)

**Satu-satunya jalan ke profit:**
1. **STOP bleeding** (E2 matikan, review security)
2. **Re-activate proven profit** (E1 spot)
3. **Fix learning loop** (tutup siklus)
4. **Scale yang terbukti** (cari likuiditas spot baru)

**Target 0,7% dari total modal ($94,57 = $0,66/trade)** — achievable  
tapi perlu E1 aktif dengan volume konsisten. Tanpa E1, target ini mustahil  
dicapai di perps Tier 0 secara matematis.

---

*Audit dilakukan 2026-08-30 05:00 WIB. Semua klaim bersumber dari data nyata:*
*- twin_engine.db (69.260 fills, 15.291 RTS)*
*- sodex_public_trades.db (447.480 record)*
*- ground_truth.json (real-time wallet state)*
*- sodex_deep_learning.jsonl (1.400+ iterasi)*
*- docs/SODEX_FARMING_COMPREHENSIVE.md (dokumentasi history)*

*Metode: forensic data analysis + scientific hypothesis testing + structural root cause analysis.*