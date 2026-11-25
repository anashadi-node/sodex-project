# ARSITEKTUR MAP — SODEX PAPER TRADING SYSTEM
# Versi 2.0 (2026-09-02) — revisi setelah riset venue + validasi statistik
# ================================================================
# Filosofi: EVIDENCE-FIRST arsitektur — setiap track punya peran ilmiah
# yang jelas, keputusan dinaikkan/turunkan berdasarkan bukti statistik.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     NORTH STAR SODEX                                │
│   Swing 1-30h · Profit ≥0,7% wallet ($0,662) per trade             │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ kompas semua keputusan
┌───────────────────────────▼─────────────────────────────────────────┐
│              KEPUTUSAN ARSITEKTUR (2026-09-02)                     │
│  1. Long-only            (SHORT disabled — P(EV>0)=3%)             │
│  2. REALWIDE exit template (SL-t=0/TP4/3x — CI95 terbukti)        │
│  3. TETAP SoDEX           (riset venue: switch = -$17 EV)          │
│  4. ATR filter DIBUANG    (data: net -$60, kontra literatur)       │
└───────────┬───────────────────────┬────────────────────────────────┘
            │                       │
   ┌────────▼────────┐    ┌─────────▼─────────┐
   │ TIER 1: PROVEN  │    │ TIER 2: EXPERIMENT │
   │  (edge CI95>0)  │    │  (kumpul data)     │
   ├─────────────────┤    ├────────────────────┤
   │ REALWIDE  n=43  │    │ SWING       n=124  │
   │  ROI +3.77%    │    │  ROI +1.79% CI~0   │
   │  CI95 [+1.26,+5.79]│  │ PARTIAL     n=117  │
   │ TWOWAY-L  n=80  │    │  ROI +1.57% CI~0   │
   │  ROI +1.51%    │    │ DONCHIAN    n=37   │
   │  CI95 [+0.05,+2.75]│  │  ROI -0.60% P=28% │
   └─────────┬────────┘    │ SPOT_SWING n=35   │
             │             │  ROI -0.22% P=43% │
             │             └─────────┬─────────┘
             │                       │
             │      n≥50 + CI95 persist
             ▼                       ▼
   ┌─────────────────────────────────────────────┐
   │          DECISION GATE (deep loop)          │
   │  bootstrap CI95 · WFE 0.5-0.7 · P(EV>0)    │
   └───────┬──────────────────────┬──────────────┘
           │                      │
   ┌───────▼────────┐    ┌────────▼────────┐
   │ GO-LIVE CAND.  │    │ KILL / FIX      │
   │ REALWIDE       │    │ DONCHIAN (P28%) │
   │ TWOWAY-LONG    │    │ SHORT (done)    │
   └───────┬────────┘    └─────────────────┘
           │
   ┌───────▼──────────────────────────────────────┐
   │         GO-LIVE PROTOCOL (belum aktif)      │
   │  dry_run=true · Pre-Deploy Review ·         │
   │  GOVERNANCE: user GO-LIVE eksplisit         │
   └──────────────────────────────────────────────┘
```

## TIER 1 — Track dengan Edge TERBUKTI (target live)

| Track | Peran | n | ROI | CI95 EV | Keputusan |
|-------|-------|:-:|:---:|:-------:|-----------|
| **REALWIDE** | Kandidat live #1 | 43 | +3,77% | [+1,26, +5,79] ✅ | n→50, lalu GO-LIVE proposal |
| **TWOWAY-LONG** | Kandidat live #2 | 80 | +1,51% | [+0,05, +2,75] ✅ | sudah qualified → bisa live |

## TIER 2 — Track Eksperimen

| Track | Peran | n | ROI | Status |
|-------|-------|:-:|:---:|--------|
| SWING | Uji TP2.5/SL1/5x vs template | 124 | +1,79% | 🟡 CI sentuh 0 — butuh ≥160 utk definitive |
| SWING_PARTIAL | Uji partial-exit engine | 117 | +1,57% | 🟡 menuju evaluasi |
| DONCHIAN | Uji breakout Donchian | 37 | -0,60% | 🔴 P(EV>0)=28% — ke arah KILL di n≥50 |
| SPOT_SWING | Uji mean-reversion 18 aset | 35 | -0,22% | 🔵 baseline — belum ada edge |

## ALUR DATA

```
Binance 1h OHLCV (sinyal)
    │
    ▼
4 track perps ──► state JSON ──► sodex_progress_report.py (harian 08:00 WIB)
    │                              │
    │                              ▼
    └──► deep learner (swing_deep_learning.jsonl) ──► learned params
                                   │
                                   ▼
                        sodex_paper_config.py (canonical, drift-check)
```

## MONITORING & GATE

1. **Harian (auto 08:00 WIB):** `sodex_progress_report.py` — ROI, n, WR, hit-rate
2. **n≥50:** tier-2 → evaluasi bootstrap; tier-1 → GO-LIVE proposal
3. **CI95 P(EV>0) < 5%:** disable track (contoh: SHORT, DONCHIAN arah)
4. **Drift check:** bandingkan track params vs `sodex_paper_config.py`

## STRUKTUR FILE (improved)

```
scripts/
├── sodex_paper_config.py      ← CANONICAL params (baru, drift-check)
├── sodex_progress_report.py    ← monitoring harian (baru)
├── paper_test_realwide.py      ← TIER 1 (proven)
├── paper_test_twoway.py        ← TIER 1 LONG (SHORT disabled)
├── paper_test_swing.py         ← TIER 2 (ZEC removed)
├── paper_test_swing_partial.py...  ← via env (PAPER_EXIT_MODE=partial)
├── paper_test_donchian.py      ← TIER 2 (kill-candidate)
└── paper_test_spot_swing.py    ← TIER 2 (18 aset)
data/
├── paper_test_*_state.json     ← track state
├── swing_deep_learning.jsonl   ← deep loop
logs/paper_test_*.log           ← runtime
reports/SODEX_*                 ← audit & riset
```

## PRIORITAS NEXT (berdasarkan arsitektur)

1. **REALWIDE n≥50** → GO-LIVE proposal (#1 kandidat, ROI 3,77% terbukti)
2. **DONCHIAN n≥50** → keputusan KILL formal (P=28% dominan)
3. **Drift-check** semua track vs config canonical (mencegah bug ASTER/PUMP/LIT class)
4. **TWOWAY-LONG n≥100** → konfirmasi stabil live #2