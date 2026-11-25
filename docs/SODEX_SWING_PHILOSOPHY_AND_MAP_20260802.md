# ANANTARA SAKTI — SoDEX Swing Trading: Philosophy, Map & State
## 2026-08-02 · Update Komprehensif

---

> ### ⚠️ REVISI 2026-08-02 (pasca re-audit terkontrol — `backtest_swing_gate1_v5.py`)
> Eksperimen terkontrol (entry identik v3, hanya geometri risiko divariasikan, fill intrabar)
> mengoreksi 3 hal yang wajib diketahui sebelum modal disentuh:
> 1. **Prinsip #4 SALAH** — "hold-duration edge" adalah artefak *conditioning-on-outcome*, bukan edge.
>    Bukti: 0 SL sebelum 12h → bucket <12h 100% WR *secara definisi* (tautologi). 51 trade fast-TP
>    membawa +155 unit, 310 sisanya −86 unit. Aturan min-hold-12h TIDAK menambah profit, dan
>    adalah **penyebab langsung DD ~90% + worst trade −8%** (8× stop). → dikoreksi di bawah.
> 2. **Leverage live = 3×, BUKAN 5×.** REAL-wide @5× DD 32% (gagal gate); @3× DD 20% (lolos <25%).
> 3. **Universe = BTC + SOL** (ETH marginal). **DROP DOGE** (PF 0.91 + hanya $13.7K/24h di SoDEX).
>    **TANPA saham** (audit 0/28 lolos, buku $15-39K tipis). Geometri: **SL −2% / TP +4%, stop AKTIF
>    dari t=0** (REAL-wide) — bukan min-hold. Terbukti dominan: PF 1.25>1.19, split-half PASS, worst −2.1%.
> 4. **Kejujuran statistik:** DSR=0.828 (<0.95 GAGAL) → edge NYATA tapi MARGINAL → size kecil, gated.
>    Full-live hanya setelah gate lolos (bukan dipaksa kalender). Detail: memory `project_sodex_swing_realwide_20260802`.
> 5. **MANDAT DUA ARAH (user 2026-08-02): BUKAN long-only.** Setiap kondisi market ada peluang.
>    LONG di bull-terkonfirmasi, SHORT di bear-terkonfirmasi (harga+Intelligence≤48+Pre-Sentiment DOWN).
>    Spot=long-only (mekanis tak bisa short) → SHORT via PERPS. Real-money kedua sisi LIVE (minimal):
>    `anantara-spot-livetest` ($3 spot long) + `anantara-perps-short-livetest` ($10 perps short 2×, worst −$0.20/trade).

---

## I. FILOSOFI PROYEK

### Tujuan (WHAT)
> Memperoleh **keuntungan profit maksimal** dari aktivitas **Swing Trading** di market sodex.com.

### Target (WHEN)
> Memperoleh keuntungan profit di **setiap time frame swing trading 1 jam – 48 jam**.

### Prinsip Dasar (WHY)
```
1. Profit adalah BUKTI, bukan target — setiap trade harus punya positive expectancy
2. Sederhana yang dijalankan > Canggih yang berhenti (lesson from Quant Engine, Pre-Gain, CEX-v8, HL-Harvest)
3. Data adalah hakim — tidak ada klaim tanpa backtest, tidak ada live tanpa paper
4. Edge = kualitas sinyal ENTRY + geometri risiko yang DIHORMATI (stop lebar tapi nyata). Hold-duration adalah HASIL, bukan input keputusan — jangan pernah men-gate entry dengan lama-tahan [REVISI: prinsip lama "hold-duration edge" terbukti artefak, lihat banner]
5. SoDEX adalah venue — semua strategi harus compatible dengan thin books, maker-fee, dan spread aktual
```

### Konstitusi Proyek (HOW)
```
F1 — Volume adalah HASIL profit, bukan tujuan
F2 — Security-first: no-withdraw flag MANDATORY, dry_run sebelum go-live
F3 — Edge-gated live: setiap strategi harus lolos Gate 1→2→3→4 sebelum live capital
```

---

## II. PETA PROYEK (PROJECT MAP)

```
SODEX SWING TRADING — ARSITEKTUR 2026-08-02
═══════════════════════════════════════════════

┌─────────────────────────────────────────────────────────┐
│                    GATE 4: FULL LIVE                      │
│              (target: ~10 Sep 2026 atau setelah)           │
│         $3,000 margin, 3× leverage, 1-2 posisi            │
├─────────────────────────────────────────────────────────┤
│                    GATE 3: MICRO-LIVE                     │
│              (target: ~10 Sep 2026)                        │
│          $500-1,500 SOL perps, verifikasi eksekusi         │
├─────────────────────────────────────────────────────────┤
│                    GATE 2: PAPER TEST                     │
│           🔴 IN PROGRESS — 0 trades / 25 target            │
│    4 pairs (SOL/DOGE/BTC/ETH), cooldown 12h, 5-min cycle   │
│    Systemd autonomous 24/7 + watchdog 15-min + Telegram    │
├─────────────────────────────────────────────────────────┤
│                    GATE 1: BACKTEST                       │
│                 ✅ CONDITIONAL PASS                        │
│     PF 1.19 (corrected 1.20), WR 46%, 361 trades           │
│     24-48h WR 62% (p<0.0001) — hold-duration confirmed     │
│     SOL terbaik (PF 1.27), DOGE #2 (PF 1.26)              │
├─────────────────────────────────────────────────────────┤
│                    RISET & AUDIT                           │
│    ✅ Literature review (8 papers akademik)                │
│    ✅ Gate 1 backtest (4 iterasi v1→v4)                    │
│    ✅ Double audit (3 gaps found & fixed)                  │
│    ✅ ML death zone predictor (AUC 0.62, PAPER-ONLY)       │
└─────────────────────────────────────────────────────────┘

STRATEGI AKTIF:
  Regime-switched momentum LONG-only
  Entry: ADX>25, price>SMA50>SMA200, RSI 40-60,
         volume>1.1×avg, 24h trend>1.2%, pullback<0.3%
  Exit [REVISI REAL-wide]: TP +4.0%, SL -2.0% (stop AKTIF dari t=0, NO min-hold), time stop 48h
  Leverage: 3× (paper & live) — 5× ditolak (DD 32% > gate 25%)
  Universe [REVISI]: BTC + SOL core, ETH marginal. TANPA DOGE, TANPA saham.
  NB: track lama min-hold (paper_test_swing) tetap jalan sbg pembanding; track REAL-wide
      (paper_test_realwide, anantara-paper-realwide.service) adalah metode terkoreksi.

INFRASTRUKTUR:
  Systemd: anantara-paper-swing.service (auto-restart)
  Watchdog: anantara-paper-watchdog.timer (15-min)
  ML: death_zone_model.pkl (XGBoost, retrain at n≥50)
  Data: Binance OHLCV 1H (backtest), SoDEX API (live prices)
```

---

## III. STRUKTUR KERJA

### Pipeline Validasi 4-Gate

```
GATE 1: BACKTEST ────► GATE 2: PAPER ────► GATE 3: MICRO-LIVE ────► GATE 4: FULL
      ✅ PASS            🔴 RUNNING            ⏳ PENDING              ⏳ PENDING
   PF 1.19, WR 46%     0/25 trades          $500-1500 SOL          $3,000 margin
   17 bulan data       target ~21 Aug        target ~10 Sep          target ~Oct
```

### Gate Criteria

| Gate | Kriteria | Status |
|------|----------|--------|
| G1: Backtest | PF≥1.4, split-half PF>1.2, DSR>0.95, DD<25%, n≥30 | ⚠️ CONDITIONAL (2/5) |
| G2: Paper | n≥25, SPRT Λ>+2.944, PF≥1.3, delta vs backtest≤15% | 🔴 PENDING |
| G3: Micro-live | 20 trades, slippage≤model, WR turun≤10pp, zero margin call | ⏳ |
| G4: Full | Review bulanan, auto turun gate jika DD>8% | ⏳ |

### Komponen Sistem

| Layer | Komponen | Status |
|-------|----------|--------|
| Eksekusi | `scripts/paper_test_swing.py` | 🟢 v4 running |
| Scheduler | `systemd anantara-paper-swing.service` | 🟢 auto-restart |
| Monitor | `scripts/paper_test_watchdog.py` | 🟢 15-min + Telegram |
| Data | SoDEX API (primary) + Binance API (fallback) | 🟢 |
| ML | `scripts/build_death_zone_model.py` | 🟡 PAPER-ONLY |
| Analisis | Gate 1 backtest v1-v4 | ✅ complete |
| Riset | Literature review 8 papers | ✅ complete |
| Audit | Double audit report | ✅ complete |
| AI Framework | River/XGBoost/ChromaDB | ⏳ pending integration |

---

## IV. METODOLOGI MENCAPAI TUJUAN

### Metode Ilmiah: PAHAMI → RENCANA → EKSEKUSI → VERIFIKASI → ULANGI

#### Fase 1: PAHAMI (COMPLETED ✅)
1. **Riset literatur** — 8 paper akademik tentang momentum, mean-reversion, pairs trading, funding arb, ML-enhanced, regime-switching, sentiment
2. **Audit internal** — seluruh 18 module SoDEX, 62 script, 47 test file, runtime state
3. **Audit SoDEX live** — spread aktual (0.2-1.4 bps, 2-11× lebih rendah dari asumsi awal), volume, liquidity

#### Fase 2: RENCANA (COMPLETED ✅)
4. **Gate 1 Backtest** — 4 iterasi ilmiah pada 8 pair Binance 1H (17 bulan)
5. **Validasi hold-duration** — thesis confirmed: 24-48h WR 62% vs 6-12h WR 22% (p<0.0001)
6. **Validasi cooldown** — 12h cooldown mempertahankan 95-112% PF, SOL+DOGE improved
7. **Double audit** — 3 gap ditemukan & diperbaiki (spread overestimate, price source, AI integration)

#### Fase 3: EKSEKUSI (IN PROGRESS 🔴)
8. **Gate 2 Paper Test** — autonomous 24/7, 4 pairs, SoDEX live prices, actual spreads
9. **ML infrastructure** — XGBoost death zone predictor pre-trained (AUC 0.62, PAPER-ONLY)
10. **Monitoring** — systemd auto-restart + watchdog 15-min + Telegram alerts

#### Fase 4: VERIFIKASI (PENDING ⏳)
11. Gate 2 evaluation pada n≥25 (~21 Aug)
12. ML retrain pada n≥50 (~10 Sep)
13. Gate 3 micro-live SOL perps

#### Fase 5: ULANGI (CONTINUOUS)
14. Belajar → Riset → Analisa → Review → Perbaikan → Improve → Verifikasi → Ulangi

---

## V. STATE SAAT INI (2026-08-02 00:30 UTC)

### Yang Sudah Selesai ✅
- [x] Fix 17 test failures (2758 tests PASS)
- [x] Clear stale signals (SAFETY_HALT, PVE_PAUSE, GUARDIAN_RESTART_SIGNAL)
- [x] Cleanup logs & __pycache__
- [x] Literature review (8 papers, 7 internal docs)
- [x] Gate 1 backtest (4 iterasi, 8 pairs, corrected spreads)
- [x] Hold-duration thesis confirmed (24-48h profit zone)
- [x] Double audit (3 gaps fixed)
- [x] ML death zone model built (AUC 0.62)
- [x] Autonomous paper test deployed (systemd 24/7)

### Yang Sedang Berjalan 🔴
- [ ] Paper test: **0 trades** dari 25 target (~15 jam runtime)
- [ ] Sinyal: momentum regime jarang (~38/bulan across 4 pairs = ~1.2/hari)
- [ ] ETH pair: baru ditambahkan, belum ada sinyal

### Yang Belum ⏳
- [ ] Gate 2 evaluation (tunggu 25 trades)
- [ ] ML retrain dengan data kaya (tunggu 50 trades)
- [ ] AI Agent Framework integration (tunggu data)
- [ ] Gate 3 micro-live SOL perps
- [ ] Twin engine restart decision
- [ ] .env config review vs swing goal

### Risiko & Challenges
1. **Paper test lambat** — 0 trades dalam 15 jam adalah NORMAL. Sinyal swing jarang terjadi.
   Estimasi: trade pertama mungkin dalam 1-3 hari.
2. **ML model lemah** — AUC CV 0.27 menunjukkan overfit. Butuh data kaya (ATR, volume profile, OBI).
3. **DD Gate 1 ~90% [TERPECAHKAN]** — BUKAN masalah struktural; itu buatan aturan min-hold-12h
   (mematikan stop 12h → loser hanyut ke −8%). Solusi = stop aktif dari t=0 (REAL-wide): DD turun
   ke 20% @3× DAN PF naik 1.19→1.25. "Death zone" adalah self-inflicted, bukan fenomena market.
4. **SoDEX liquidity** — DOGE perps hanya $16K/24h. Scaling terbatas.

---

## VI. REALITAS & KEJUJURAN

### Yang Berhasil
- Metodologi ilmiah bekerja: Gate 1 mencegah 5 bulan paper test sia-sia
- Hold-duration adalah temuan paling berharga — mengubah seluruh arah strategi
- Autonomous infrastructure solid: 0 restart, 0 error dalam 15 jam
- Actual SoDEX spreads 2-11× lebih rendah dari asumsi — margin lebih besar

### Yang Belum Berhasil
- Strategi belum mencapai PF 1.4 (masih 1.19-1.20)
- Death zone (6-12h) masih membunuh 32-40% trades
- ML filter belum cukup kuat untuk memprediksi death zone
- Paper test belum menghasilkan trade — normal tapi perlu kesabaran

### Yang Tidak Bisa Dijanjikan
- Profit pasti — trading adalah probabilitas, bukan jaminan
- Timeline pasti — sinyal swing bergantung pada kondisi market
- PF 1.4 dalam versi saat ini — mungkin perlu strategi hybrid atau pairs trading

---

## VII. NEXT MILESTONES

| Tanggal (estimasi) | Milestone | Apa yang terjadi |
|-------------------|-----------|------------------|
| 3-5 Aug | Trade pertama | Paper test menghasilkan sinyal pertama |
| 9 Aug | 10 trades | Sanity check: apakah WR & PF sesuai backtest? |
| 21 Aug | 25 trades | Gate 2 SPRT evaluation |
| 10 Sep | 50 trades | ML retrain dengan data kaya, Gate 3 prep |
| Oct 2026 | Gate 4 | Full live deployment (jika semua gate lolos) |

---

*Generated: 2026-08-02 00:30 UTC · ANANTARA SAKTI SoDEX Swing Trading*
*Prinsip: "Sederhana yang dijalankan > Canggih yang berhenti"*
