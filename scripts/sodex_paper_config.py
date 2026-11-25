# SODEX — PAPER STRATEGY CANONICAL CONFIG
# Single source of truth untuk semua parameter paper track.
# Dibuat 2026-09-02 setelah riset venue + validasi statistik bootstrap.
#
# TUJUAN: mencegah drift parameter antar track (bug class yang pernah terjadi:
# ASTER/PUMP/LIT ada di SWING tapi tidak di track lain; SPREAD tidak konsisten).
# File ini adalah BLUEPRINT — jangan di-import otomatis ke track berjalan
# (ponytail: jangan sentuh yang sedang bekerja). Diff manual untuk deteksi drift.

import os

# ═══════════════════════════════════════════════════════════════
# BAGIAN 1 — NORTH STAR
# ═══════════════════════════════════════════════════════════════
TARGET_MIN_PCT = 0.008          # ≥0.8% wallet per 30h window (North Star SODEX, user GO 27-Sep)
REAL_WALLET = float(os.environ.get("SODEX_TOTAL_WALLET", "108.10"))
TARGET_MIN_USD = REAL_WALLET * TARGET_MIN_PCT  # derived from runtime wallet

# ═══════════════════════════════════════════════════════════════
# BAGIAN 2 — UNIVERSE PERPS (SoDEX, terverifikasi 2026-09-01)
# ═══════════════════════════════════════════════════════════════
PERPS_PAIRS = [
    "BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE",
    "BCH", "ONDO", "LINK", "AAVE", "SUI", "UNI", "ADA",
    "TRX", "ENA", "ASTER", "PUMP", "LIT",   # +3 pair baru per user
]
# Extensi per track (bukan semua track): ARB/AVAX/SILVER/XAUT di TWOWAY/REALWIDE/DONCHIAN,
# ZEC hanya di DONCHIAN (dihapus dari SWING karena EMERGENCY_SL 6/9).
# 2026-09-02: HYPE & ENA DIBLOCK dari DONCHIAN (anti-edge): HYPE n=6 WR 17% EV -$25.56,
# ENA n=5 WR 20% EV -$9.62 — kriteria block penuh (n≥5, WR<40%, EV<0). Sisa 26 trade
# DONCHIAN = +$14.12 (positif). Pair tetap dipantau di track lain (HYPE di SWING/REALWIDE,
# ENA di SWING/REALWIDE/TWOWAY).
TRACK_EXTRA_PAIRS = {
    "TWOWAY":   ["ARB", "AVAX", "SILVER", "XAUT"],
    "REALWIDE": ["ARB", "AVAX", "SILVER", "XAUT"],
    "DONCHIAN": ["ARB", "AVAX", "SILVER", "XAUT", "ZEC"],
}

# Binance symbol per pair (sumber sinyal 1h)
BN_SYMBOLS = {p: p + "USDT" for p in PERPS_PAIRS}
BN_SYMBOLS.update({"SILVER": "XAGUSDT", "XAUT": "XAUTUSDT"})

# SoDEX symbol per pair (venue eksekusi)
SODEX_SYMBOLS = {p: f"{p}-USD" for p in PERPS_PAIRS}

# ═══════════════════════════════════════════════════════════════
# BAGIAN 3 — SPREAD MODEL (live-measured 2026-08-29/31)
# ═══════════════════════════════════════════════════════════════
# Sumber: orderbook + ticker SoDEX. Thin-book (top-of-book <$550/side) → 8bps.
SPREAD_MODEL = {
    "BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035, "XRP": 0.0002,
    "HYPE": 0.0008,  "DOGE": 0.0002, "BCH": 0.0002,  "ONDO": 0.000285,
    "LINK": 0.0002,  "AAVE": 0.0002, "SUI": 0.0008,  "ADA": 0.000497,
    "TRX": 0.0002,   "UNI": 0.000227,"ENA": 0.000614,"XAUT": 0.000605,
    "SILVER": 0.0008,"ARB": 0.0002,  "AVAX": 0.0002,
    "ASTER": 0.0004, "PUMP": 0.0004, "LIT": 0.0008,   # +3 baru
}
MAKER_FEE_RT = 0.00024            # round-trip maker fee (0.0108%×2 + margin)

# ═══════════════════════════════════════════════════════════════
# BAGIAN 4 — GEOMETRI EXIT PER TRACK (hasil validasi bootstrap)
# ═══════════════════════════════════════════════════════════════
#   REALWIDE  : SL-2% t=0, TP-4%, 3x, time-stop 30h → CI95 EV>0 ✅ TERBUKTI
#   TWOWAY-L  : sama + SHORT disabled → CI95 EV>0 ✅ TERBUKTI
#   PARTIAL   : 50% profit di +1.2%, sisa TP2.5/SL-protect, SL t=0 (fix 2026-09-04)
#   SWING     : min-hold FIX 2026-09-04: 12h→0h (SL t=0). SEBELUM: 28% trade
#               (37/132) kena EMERGENCY_SL krn SL normal ditahan 12h. Samakan
#               REALWIDE yg 0% emergency SL, WR 60.8%, ROI +4.23% (role model).
#   DONCHIAN  : breakout, SL-2/TP-4 → P(EV>0)=28% 🔴 kill-candidate
#   SPOT_SWING: v3 RETIRED 2026-09-04 (n=36, PnL -$14.32, jendela gempa 4h).
#               Digantikan SPOT_SWING_v4 (kombinasi CEX momentum+ADX+regime,
#               SL t=0, mode adaptif) — lihat entry SPOT_SWING_v4 di bawah.

GEOMETRY = {
    "REALWIDE":   {"tp": 0.040, "sl": 0.020, "lev": 3, "min_hold": 0,  "time_stop": 30},
    "TWOWAY_LONG": {"tp": 0.040, "sl": 0.020, "lev": 3, "min_hold": 0,  "time_stop": 30},
    "SWING_PARTIAL": {"tp": 0.025, "sl": 0.010, "lev": 5, "min_hold": 0, "time_stop": 30,
                      "partial_pct": 0.012, "partial_frac": 0.5},
    "SWING":      {"tp": 0.025, "sl": 0.010, "lev": 5, "min_hold": 0,  "time_stop": 30},
    "DONCHIAN":   {"tp": 0.040, "sl": 0.020, "lev": 3, "min_hold": 0,  "time_stop": 30},
    # SPOT_SWING v3 RETIRED 2026-09-04 — service dihentikan, digantikan v4.
    # SPOT_SWING_v4 (2026-09-03): kombinasi CEX (momentum+ADX+regime, long-only),
    # SL AKTIF DARI t=0 (fix jendela gempa -$32.91), filter likuiditas $3K/24h,
    # size $100 (kurang slippage). State v2 terpisah. Dasar: CEX 'momentum+adx+
    # regime' WR 100% n=12 avg +2.3% + root cause analysis 35 trade.
    # UPDATED (2026-09-03): ADX H/L sejati (bug close-based fix → ADX <25), ambang
    # ADX 20 (relaksasi), momentum OR (c>SMA50 ATAU mom5>0.5%), regime EMA50+mom6
    # (adaptif bukan SMA200 kaku → 0 fire), MODE ADAPTIF: saat BTC down tetap long
    # pair independen-bull (UNI/TON/LTC) max 1 posisi, FAPI fallback HYPE/XAUT.
    "SPOT_SWING_v4": {"tp": 0.025, "sl": 0.015, "lev": 1, "min_hold": 0,
                      "time_stop": 30, "mom_ret5": 0.005, "adx_min": 20,
                      "min_volume": 3000, "pos_usd": 100,
                      "regime_ema50": True, "adaptif_mode": True,
                      "pairs": ["vBTC","vTON","vETH","vHYPE","vXRP","vLINK","vUNI"]},
}

# ═══════════════════════════════════════════════════════════════
# BAGIAN 5 — SIZING (riset literatur + data)
# ═══════════════════════════════════════════════════════════════
# Risk per trade: 1-2% wallet (half-Kelly guidance). Current $100/3x @ SL2%
# = $2 risk = 2.1% wallet — di puncak rentang aman. JANGAN naikkan.
NOTIONAL_DEFAULT = 100.0
LEVERAGE_DEFAULT = 3
RISK_PCT_WALLET = 0.021          # ~2.1% — ceiling aman
MAX_POSITIONS = 6                # cap koncurrent exposure

# ═══════════════════════════════════════════════════════════════
# BAGIAN 6 — LESSON LEARNED (scientific, jangan ulangi)
# ═══════════════════════════════════════════════════════════════
LESSONS = {
    "short_disable": "SHORT WR 29.7% (n=37), CI95 P(EV>0)=3% → disable 2026-09-02. "
                     "Literatur + data = 2 bukti independen: long-only.",
    "atr_filter_harmful": "ATR entry filter (skip jika ATR>1.5%) MERUGIKAN: cegah $259 "
                          "loss EMERGENCY tapi buang $319 win TP → net -$60. "
                          "JANGAN pakai ATR filter sebagai gate entry.",
    "geometry_fix": "EMERGENCY_SL (26.7% di SWING) bukan masalah entry — masalah geometry "
                    "(min-hold 12h tanpa SL). REALWIDE (SL t=0) menghilangkannya.",
    "venue_switch": "Riset 2026-09-02: TETAP SoDEX. HL gain fee cuma $3/bln vs migrasi $17. "
                    "Variational/Ondo/Paradex tidak siap untuk bot.",
}
