# ANANTARA SAKTI — SoDEX FARMING: DOKUMENTASI LENGKAP A-Z

> **Status:** 2026-07-03 | **Mode Aktif:** MODE11-BEARDOWN | **Volume:** $461K+
> **Dokumentasi ini adalah catatan JUJUR — termasuk semua kegagalan.**

---

## BAGIAN 1 — GAMBARAN BESAR

### 1.1 Apa Itu SoDEX Farming?

SoDEX Farming adalah sistem trading otomatis di **SoDEX** (DEX perpetuals + spot) yang bertujuan menghasilkan **volume transaksi** ($1M+/minggu) dan **profit real**. Sistem berjalan 24/7 melalui daemon Python (`anantara_daemon.py`) yang dijalankan oleh systemd.

### 1.2 Tujuan Ganda

| Tujuan | Target | Status |
|--------|--------|:------:|
| Volume transaksi | $1,000,000/minggu | ✅ Tercapai ($2.3M/minggu projected) |
| Profit real (PNL) | > $0 (positif) | ❌ Belum tercapai |
| Rasio volume/biaya | 1:8,650 | ❌ 1:4,630 (mentok matematis) |
| Zero force-close | 0 taker close | ✅ Tercapai |

### 1.3 Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                    anantara_daemon.py                        │
│  (systemd service, 24/7, APScheduler)                       │
├─────────────────────────────────────────────────────────────┤
│  job_sodex_scalp (4 menit)    ← MODE11 BEARDOWN (PERPS)     │
│  job_sodex_spot_farm (15 menit) ← Spot Autofarm (SPOT)      │
│  job_sodex_monitor (2 menit)  ← Monitoring                  │
│  Telegram long-polling        ← /beardown, /sodexprofit     │
├─────────────────────────────────────────────────────────────┤
│  sodex_farming.py (168KB)     ← Semua mode trading perps    │
│  sodex_autofarm.py (40KB)     ← Spot autofarm v3.1          │
│  sodex_spot_farm.py (6KB)     ← Spot legacy (deprecated)    │
│  sodex_profit_report.py (7KB) ← /sodexprofit & /sodexfix    │
└─────────────────────────────────────────────────────────────┘
```

### 1.4 Akun SoDEX

| Item | Value |
|------|-------|
| Address | `0x4a464b82b1c1233791351483c90c53e2a2fbc799` |
| Account ID | 180570 |
| Maker fee | **0.0108%** (Tier 0 + Staking Tier 2 diskon 10%) |
| Taker fee | 0.036% |
| Fee tier | 0 (perlu $5M/14hari untuk Tier 1) |
| Staking tier | 2 (10% diskon) |
| Maker rebate | 0 (belum qualify) |

---

## BAGIAN 2 — SEMUA MODE TRADING

### 2.1 Daftar Mode

| Mode | Nama | Market | Strategi | Status |
|:----:|------|--------|----------|:------:|
| 1 | TAKER | Perps | Market open + close | ❌ Tidak digunakan |
| 2 | MAKER | Perps | Patient maker round | ❌ Digantikan MODE11 |
| 3 | PARALLEL | Perps | Multi-symbol parallel | ❌ |
| 4 | RATIO | Perps | BTC+SILVER ultra-short | ❌ |
| 5 | OBI | Perps | Order Book Imbalance dynamic | ❌ Dinonaktifkan |
| 6 | MM HYBRID | Perps | Simultaneous BUY+SELL | ❌ |
| 7 | RADICAL | Perps | OBI + Quality Score | ❌ Dinonaktifkan |
| 8 | DELTA-NEUTRAL | Perps | Pre-Gain integrated | ❌ |
| 9 | DUAL | Perps | MODE7 + MODE8 parallel | ❌ |
| 10 | DSSC | Perps | Dual-Side Spread Capture | ❌ 0% dual rate |
| **11** | **BEARDOWN** | **Perps** | **Regime-aware patient MM** | **✅ AKTIF** |
| — | Spot Autofarm | Spot | PEPE/USDC two-sided maker | 🟡 Paused (event risk) |
| — | E1 (historical) | Spot | PEPE/SHIB/SUI maker | 🔴 Mati (likuiditas) |

### 2.2 MODE11 BEARDOWN — Detail

**Konfigurasi Saat Ini:**
```
Mode:           11 (BEARDOWN)
Symbols:        6 (NEAR, WIF, SILVER, ADA, ENA, XPL)
Margin:         $75/symbol
Leverage:       5×
Notional:       $375/symbol, $2,250/siklus
Interval:       4 menit
Open wait:      90 detik
Close wait:     120 detik
Stop-loss:      35% margin
Drift target:   0.05% (close above market)
LONG_BIAS:      ON (semua LONG di NEUTRAL)
Cost cap:       $300/hari
```

**Cara Kerja:**
1. Baca regime market (BEAR/BULL/NEUTRAL) dari intelligence JSONL
2. BEAR → semua SHORT (sell-first)
3. BULL → semua LONG (buy-first)
4. NEUTRAL + LONG_BIAS → semua LONG
5. Entry: maker order di bid (buy) atau ask (sell)
6. Close: 2-phase — drift target (60s) → breakeven market (60s) → taker (last resort)
7. Spread gate: 4× baseline per-symbol
8. Momentum gate: 0.3-0.5% tergantung regime

### 2.3 Spot Autofarm v3.1 — Detail

**Konfigurasi:**
```
Pair:           PEPE/USDC (satu-satunya pair dengan spread >0.30%)
Capital:         $300
Strategy:       Two-sided post-only maker (gtx)
Spread min:     0.25-0.35% (dynamic by regime)
Intel:          Fear & Greed based sizing (0.5x-2.0x)
Circuit breaker: 3 consecutive losses → stop
Macro CB:       F&G >85 + liquidation cascade
```

**Kenapa Tidak Jalan:**
1. EVENT_RISK_RED — berita Trump/Iran memicu shock guard
2. Adaptive policy — memblokir SPOT_LONG (data historis negatif)
3. Likuiditas PEPE/USDC tipis — order tidak terisi
4. Multi-layer security terlalu konservatif

---

## BAGIAN 3 — SEJARAH & GARIS WAKTU

### 3.1 Timeline Project

| Tanggal | Event | Detail |
|---------|-------|--------|
| 2026-05-24 | Data OBI dikumpulkan | 317K+ snapshot, 310K+ trades |
| 2026-06-08 | Spot farm deprecated | Digantikan sodex_autofarm.py v3.1 |
| 2026-06-21 | **E1 Spot LAUNCH** | net=+0.402%, vol_proj=$1.8M |
| 2026-06-23 | **E1 PEAK PROFIT** | net=+0.665%, vol=$11.7M/hari |
| 2026-06-24 | **E1 MAX PROFIT** | net=+2.446%, vol=$18.9M/hari, 1426 fills/jam |
| 2026-06-25 | **E1 MATI** | Likuiditas pair kering, 2766 dead alerts |
| 2026-06-27-29 | E1 recovery kecil | net +0.5-0.9%, vol kecil |
| 2026-07-01 | BEARDOWN (MODE11) lahir | Gantikan MODE7 yang rugi |
| 2026-07-01 | Close-leg fix | post_only=False → 0 force-close |
| 2026-07-02 | LONG_BIAS + drift-capture | Optimalisasi untuk sideways-up |
| 2026-07-02 | 11→6 simbol | Pangkas yang tidak perform |
| 2026-07-02 | PEPE spot first fill | 0.41% spread, net +0.24% |
| 2026-07-03 | /sodexprofit & /sodexfix | Telegram commands |

### 3.2 E1 Spot — Era Keemasan

**Periode: 21-24 Juni 2026**

E1 adalah engine spot trading yang paling sukses dalam sejarah project ini:

| Hari | Net Maks | Volume | Fills/jam | Status |
|------|:--------:|:------:|:---------:|:------:|
| Jun 21 | +0.405% | $6.7M | 1448 | 🟡 Warming up |
| Jun 22 | +0.095% | $10.8M | 1761 | 🟡 Marginal |
| **Jun 23** | **+0.665%** | **$11.7M** | **1520** | 🟢 **PROFITABLE** |
| **Jun 24** | **+2.446%** | **$18.9M** | **1426** | 🟢 **MAX PROFIT** |

**Pair Performance (SCIENCE data, 50 sampel):**
- PEPE/USDC: **50/50 PROFITABLE** (100%!)
- SHIB/USDC: 50/50 UNCERTAIN
- ARB/USDC: 50/50 LOSING
- XLM/USDC: 50/50 LOSING

**Mengapa E1 Sukses:**
1. Spot spread 0.28-0.41% vs fee 0.07% = net +0.21-0.34%
2. Two-sided maker strategy menangkap spread natural
3. Market sideways → osilasi harga → dual-fill sering terjadi
4. Jam aktif: 06-10 UTC (13-17 WIB) — sesi Asia/Eropa

**Mengapa E1 Mati:**
1. Likuiditas pair spot (PEPE, SHIB) mengering setelah 25 Juni
2. Order tidak terisi → engine stalled
3. Autofarm replacement (v3.1) terlalu banyak security layer

---

## BAGIAN 4 — MASALAH & TANTANGAN

### 4.1 Masalah Struktural (Belum Terselesaikan)

#### A. PERPS TIDAK BISA PROFIT DI TIER 0

```
Fee round-trip:   0.0216% (maker 0.0108% × 2)
Spread ditangkap: 0.003% (max)
Net per trade:    -0.0186% → SELALU RUGI SECARA MATEMATIS
```

Ini adalah **akar semua masalah**. Tidak ada strategi perps yang bisa profit selama:
- Fee > spread yang bisa ditangkap
- Tidak ada Maker Rebate (platform tidak bayar kita)
- Tier fee masih 0

**Satu-satunya jalan keluar:**
1. Tier upgrade → Tier 4 (maker 0%) = infinite ratio
2. Maker Rebate → platform bayar kita untuk trading
3. Spot trading → spread 100× lebih lebar dari perps

#### B. SPOT LIKUIDITAS TERLALU TIPIS

- Hanya PEPE/USDC yang memiliki spread >0.30%
- Tapi likuiditas tidak cukup untuk eksekusi konsisten
- SHIB, SUI, DOGE — spread tidak terukur atau tidak cukup
- Stocks (NVDA, AAPL, dll) — status HALT

#### C. RASIO 1:4,630 MENTOK MATEMATIS

```
Rasio = Volume / Biaya = 1 / (makerFee × 2) = 1 / 0.000216 = 4,630
```

Target 1:8,650 hanya bisa dicapai dengan:
- Tier 4 (maker 0.000%) → rasio infinite
- Konvensi 1-leg → 1/0.000108 = 9,259 ≈ target

#### D. SECURITY LAYERS TERLALU AGRESIF

Spot autofarm memiliki 3 lapis keamanan yang MEMBLOKIR trading:
1. **Event Shock Guard** — RED level untuk berita Trump/Iran (padahal berita BULLISH)
2. **Adaptive Policy** — memblokir SPOT_LONG berdasarkan data historis
3. **Route Gates** — BLOCK_LIVE bahkan saat market bagus

Bypass sudah dicoba (`SODEX_EVENT_GUARD_FORCE_ALLOW=1`, `SODEX_ADAPTIVE_POLICY_DISABLE=1`) tapi tidak konsisten.

### 4.2 Masalah Teknis (Sudah Diperbaiki)

| Masalah | Dampak | Solusi | Status |
|---------|--------|--------|:------:|
| Close leg gtx (post-only) | Stuck position → force-close → rugi taker | `post_only=False` | ✅ Fixed |
| ARB-USD force-close cascade | 75 force-close/24jam | Drop ARB dari simbol | ✅ Fixed |
| Cycle interval terlalu rapat | Job skipped, stuck | 3→4 menit | ✅ Fixed |
| State persistence bug | KeyError pnl_total | `setdefault()` | ✅ Fixed |
| DASH-USD 0% fill | Buang biaya tanpa hasil | Drop DASH | ✅ Fixed |
| FIL-USD 41% fill | Buang biaya | Drop FIL | ✅ Fixed |

### 4.3 Masalah Operasional

| Masalah | Detail |
|---------|--------|
| Restart daemon = downtime | Setiap restart ~6 menit tanpa trading |
| Auto-recovery loss | Setiap restart ada recovery trade yang rugi |
| Weekend slowdown | Volume turun 30-50% saat weekend |
| Market pagi sepi | Jam 05-08 WIB fill rate rendah |
| Hermes timeout | Intel server kadang unreachable |

---

## BAGIAN 5 — MODE & SIMBOL — ANALISIS MENDALAM

### 5.1 Perbandingan Semua Mode (Data 7 Hari)

| Mode | Fill Rate | Dual Rate | Taker Rate | Profit? | Rating |
|------|:---------:|:---------:|:----------:|:-------:|:------:|
| MODE11 BEARDOWN | 85% | N/A | 0% | ❌ (struktural) | ⭐⭐ |
| MODE10 DSSC | 100% | **0%** | 0% | ❌ | ❌ |
| MODE7 RADICAL | 60% | N/A | 5% | ❌ | ⭐ |
| MODE2 MAKER | 70% | N/A | 3% | ❌ | ⭐ |
| E1 SPOT (historis) | 95%+ | N/A | 0% | ✅ +0.27% | ⭐⭐⭐ |

### 5.2 Perbandingan Simbol (Data 6 Jam)

| Simbol | Fill Rate | Volume 6H | Avg Fill | Spread | Status |
|--------|:---------:|:---------:|:--------:|:------:|:------:|
| SILVER-USD | 96% | $14,006 | $400 | 13bps | ✅ Volume king |
| WIF-USD | 92% | $12,673 | $422 | 16bps | ✅ Solid |
| NEAR-USD | 94% | $11,990 | $428 | 11bps | ✅ Konsisten |
| ADA-USD | 71% | $9,281 | $404 | 14bps | 🟡 Borderline |
| XPL-USD | 75% | $7,786 | $458 | 31bps | 🟡 Wide spread |
| ENA-USD | 64% | $5,267 | $658 | 34bps | 🟡 Low fill |
| WLFI-USD | 100% | $767 | — | 50bps | 🔴 Tiny vol |
| BTC-USD | 100% | $1,564 | — | 0.3bps | 🔴 No spread |
| ETH-USD | 100% | $1,484 | — | 1.5bps | 🔴 No spread |
| DASH-USD | 20% | $229 | — | 16bps | 🔴 DROPPED |
| FIL-USD | 41% | $3,323 | — | 32bps | 🔴 DROPPED |
| ARB-USD | 96% | $6,601 | — | 30bps | 🔴 DROPPED (stuck) |

### 5.3 Spot Pair Analysis

| Pair | Status | Spread | E1 Data | Likuiditas |
|------|:------:|:------:|:-------:|:----------:|
| PEPE/USDC | TRADING | 0.28-0.41% | 50/50 PROFIT | Tipis |
| SHIB/USDC | TRADING | ~0.18% | 50/50 UNCERTAIN | Sangat tipis |
| SUI/USDC | TRADING | Unknown | No data | Tidak diketahui |
| DOGE/USDC | TRADING | Unknown | No data | Tidak diketahui |
| HYPE/USDC | TRADING | Unknown | No data | Tidak diketahui |
| SOSO/USDC | TRADING | Unknown | No data | Token SoDEX |

---

## BAGIAN 6 — TELEGRAM COMMANDS

| Command | Fungsi | Handler |
|---------|--------|---------|
| `/beardown` | BEARDOWN dashboard (volume, PNL, regime) | `_cmd_beardown` |
| `/beardown-pause` | Pause BEARDOWN | `_cmd_beardown_pause` |
| `/beardown-resume` | Resume BEARDOWN | `_cmd_beardown_resume` |
| `/sodexprofit` | Profit report + account value | `_cmd_sodex_profit` |
| `/sodexfix` | Safe repair (signals, watchdog) | `_cmd_sodex_fix` |
| `/sodex` | SoDEX status umum | `_cmd_sodex` |
| `/sodex-ratio` | Ratio report | `_cmd_sodex_ratio` |
| `/sodex-eval` | Monitoring & Evaluasi | `_cmd_sodex_eval` |
| `/sodexon` | Enable SoDEX farming | `_cmd_sodex_on` |
| `/sodexoff` | Disable SoDEX farming | `_cmd_sodex_off` |

---

## BAGIAN 7 — STRUKTUR FILE

```
anantara/
├── sodex_farming.py        168KB — Semua mode perps (MODE1-11)
├── anantara_daemon.py      272KB — Daemon utama + Telegram
├── sodex_autofarm.py        40KB — Spot autofarm v3.1
├── sodex_spot_farm.py        6KB — Spot legacy (deprecated)
├── sodex_event_shock_guard   — Event risk monitor
├── sodex_spot_governor       — Spot trade governor
├── sodex_intel_layer         — Fear & Greed intel
└── sodex_state_io            — State persistence

scripts/
├── sodex_profit_report.py    7KB — /sodexprofit & /sodexfix
├── sodex_e1_autopilot.py  1069 lines — E1 monitor (mati)
├── sodex_spot_daemon.py    723 lines — Spot daemon wrapper
├── spot_profit_maximizer    — 7-hour profit loop (eksperimental)
└── analyze_spot_maker.py     — Spot analyzer

logs/
├── e1_autopilot.log      4111KB — E1 historical data
├── automon.log           3183KB — Autonomous monitor
├── beardown_cron.log       15KB — BEARDOWN cron reports
├── sodex_84h_supervisor  1734KB — 84h supervisor
└── spot_profit_maximizer   — Maximizer logs

data/
├── beardown_state.json        — BEARDOWN persistent state
├── sodex_ratio_state.json     — General SoDEX state
└── sodex/research/
    └── autonomous_status.json — Event risk cache
```

---

## BAGIAN 8 — STATE & PERSISTENCE

### 8.1 BEARDOWN State (`beardown_state.json`)

```json
{
  "vol_total": 461417.0,
  "cost_total": 99.67,
  "pnl_total": -4.68,
  "fills_total": 525,
  "maker_legs": 0,
  "taker_closes": 0,
  "skips_total": 0,
  "symbol_skips": {},
  "started_at": "2026-07-01T04:26:06+00:00",
  "updated_at": "...",
  "last_cycle_at": "..."
}
```

### 8.2 General SoDEX State (`sodex_ratio_state.json`)

```json
{
  "week_vol": 767227.33,
  "week_cost": 5162.65,
  "vol_today": 92459.21,
  "cost_today": 1490.99
}
```

---

## BAGIAN 9 — FEE STRUCTURE & TIER PATH

### 9.1 Fee Saat Ini

```
Tier 0 + Staking Tier 2 (10% diskon):
  Maker: 0.012% × 0.90 = 0.0108%
  Taker: 0.040% × 0.90 = 0.036%
```

### 9.2 Tier Progression (14-day rolling)

| Tier | Volume | Maker Fee | Hari (est.) | Savings |
|:----:|:------:|:---------:|:-----------:|:-------:|
| 0 | ≤$5M | 0.0108% | — | — |
| 1 | >$5M | 0.010% | ~23 hari | 0.0008% |
| 2 | >$25M | 0.006% | ~97 hari | 0.0048% |
| 3 | >$100M | 0.002% | ~364 hari | 0.0088% |
| 4 | >$500M | **0.000%** | ~1939 hari | **0.0108%** |

### 9.3 Maker Rebates (Platform BAYAR Anda)

| Tier | Maker Volume Share | Fee |
|:----:|:-------------------|:---:|
| 1 | >0.50% platform | **-0.001%** |
| 2 | >1.50% platform | **-0.002%** |
| 3 | >3.00% platform | **-0.003%** |

---

## BAGIAN 10 — PELAJARAN & KESIMPULAN

### 10.1 Apa yang Berhasil

1. **BEARDOWN volume engine** — menghasilkan $2.3M/minggu, 0 force-close
2. **Close-leg fix** — `post_only=False` mengeliminasi stuck positions
3. **LONG_BIAS** — adaptasi otomatis ke market BULL
4. **E1 Spot (historis)** — +2.446% net di peak, bukti bahwa spot BISA profit
5. **Per-symbol optimization** — pangkas yang tidak perform
6. **Telegram commands** — monitoring real-time

### 10.2 Apa yang Gagal

1. **Profit perps** — tidak mungkin di Tier 0 (matematis)
2. **Spot autofarm** — terlalu banyak security layer, tidak bisa jalan
3. **Drift-capture** — target 0.10% terlalu tinggi, mayoritas fallback
4. **MODE10 DSSC** — 0% dual rate di trending market
5. **PEPE loop** — eksekusi tidak konsisten
6. **7-hour maximizer** — PNL tracking broken, tidak ada profit real

### 10.3 Akar Semua Masalah

```
SATU AKAR MASALAH: Fee > Edge

Di perps: Fee 0.0216% > Spread 0.003% → rugi struktural
Di spot:  Fee 0.07% < Spread 0.30% → BISA profit
Tapi:     Spot tidak likuid → tidak bisa dieksekusi

Paradoks: Di mana ada profit (spot), tidak ada likuiditas.
          Di mana ada likuiditas (perps), tidak ada profit.
```

### 10.4 Jalan Keluar

| Prioritas | Solusi | Timeline |
|:---------:|--------|:--------:|
| 1 | Volume agresif → Tier 1 (23 hari) | Juli 2026 |
| 2 | Cari pair spot likuid pengganti PEPE | Riset ongoing |
| 3 | Kontak SoDEX untuk Maker Rebate | Tergantung respons |
| 4 | Tier 4 (maker 0%) → semua strategi profit | ~5 tahun |
| 5 | Tambah modal → percepat tier climb | Jika memungkinkan |

---

## BAGIAN 11 — KONFIGURASI SAAT INI

### 11.1 .env Key Settings

```bash
SODEX_SCALP_MODE=11                    # BEARDOWN
SODEX_MODE11=1
SODEX_MODE11_SYMBOLS=NEAR-USD,WIF-USD,SILVER-USD,ADA-USD,ENA-USD,XPL-USD
SODEX_MODE11_MARGIN=75                 # $75/symbol
SODEX_MODE11_LEVERAGE=5
SODEX_MODE11_DRIFT_TARGET=0.0005       # 0.05%
SODEX_MODE11_LONG_BIAS=1               # NEUTRAL→LONG
SODEX_MODE11_STOP_LOSS=0.35
SODEX_SCALP_INTERVAL_MINUTES=4
SODEX_SCALP_DAILY_COST_CAP=300
SODEX_EVENT_GUARD_FORCE_ALLOW=1
SODEX_SPOT_FARM_LIVE=1
SPOT_FARM_CAPITAL=300
```

### 11.2 State Files

```bash
~/.local/share/anantara/beardown_state.json     # BEARDOWN session
~/.local/share/anantara/sodex_ratio_state.json  # General SoDEX
```

---

*Dokumentasi ini dibuat 2026-07-03. Mencakup seluruh perjalanan project SoDEX Farming dari awal hingga saat ini, termasuk semua kegagalan, perbaikan, dan pelajaran. Jujur, lengkap, tidak ada yang ditutupi.*
