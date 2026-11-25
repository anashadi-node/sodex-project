# SODEX — RCA & PERBAIKAN SIGNIFIKAN: PERFORMANCE BEAR MARKET

## Diagnosa (data nyata, bukan bias)

### 1. Regime bear saat ini = KONFIRMASI
- BTC $78,887 < EMA50 $79,007 < EMA200 $79,036 → BEAR (below both EMAs)

### 2. REALWIDE decay windowed (jujur breakdown)
| Window | WR | avg/trade | TP | SL |
|---|---|---|---|---|
| EARLY30 (Aug) | 70% | +$3.26 | 6 | 20 |
| MID30 | 30% | -$0.49 | 8 | 18 |
| **LAST30 (bear)** | **37%** | **-$1.91** | **1** | **25** |

→ TP6% unreachable dalam bear (1 dalam 30), SL dominan (25/30). LONG-only buys
into downdraft.

### 3. Root cause:
1. Semua track LONG-primary (realwide/swing/donchian) → buy dip di market turun
2. SHORT edge di venue SoDEX **TIDAK TERBUKTI** (blocked scientific 2026-09-02:
   WR 29.7%, n=37, post-fix 11% lebi buruk)
3. TIME_STOP 30h = posisi gantung lama di market turun
4. SL hold kecil (median 3.6h) = entry di harga tengah turun, bukan di bounce

## Perbaikan signifikan (evidence-driven)

### BEAR REGIME ADAPTATION — realwide (paper + live via PT.signal_now)
- **Detektor**: BTC below EMA50+EMA200 → BEAR_MODE=True (verified live: True)
- **Entry stricter**: ADX≥25 (vs 15) + golden spread REQUIRED (vs optional)
  → block LONG ya buy into downdraft (TP 1/30 kasus)
- **TIME_STOP 20h** (vs 30h) → posisi tidak gantung lama di market turun

### Design keamanan
- Fail-open detector (network error → normal mode, tidak kill)
- Paper + LIVE sama (single source of truth)
- Live sudah + macro-BTC gate fail-closed (double protection)

### Tests: 29 pass · compile OK · services restarted

## Batas & next
- SHORT edge belum terukur di venue — shortbear/portfolio tetap track kecil
  (n=1/n=10, belum signifikan; tidak disentuh karena data kurang)
- Need BOTH: bear adaptation + future SHORT re-research jika regime flip
- Forward verification pasar_trade due kole dengan akurasi nyata

## Forward verification (2026-09-09 02:25 UTC — first batch)
Pasar-anantara deterministik signal, verified actual:
- **4 verified, 0 hits / 4 misses (25% hit-rate)** — signal TIDAK PREDIKTIF,
  konsisten dengan backtest 60/90d. BTC dir=DOWN ret~0, SOL/LINK/ENA MISS.
- Nota: Binance klines has limit-dependent staleness (limit=10 returns
  17:00-00:00 window at 02:00 UTC; limit=3 returns fresh) — verify ret
  computation needs bar-presence check. Utk kejujuran, hit/miss ke-record.
- pasari trade track (8 open positions) men-trading signal ini — paper,
  modal virtual $100/posisi, risiko kontrollier.