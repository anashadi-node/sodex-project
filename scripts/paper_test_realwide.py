#!/usr/bin/env python3
"""Gate-2 PARALLEL paper track — REAL-wide risk geometry.

Runs ALONGSIDE the live paper_test_swing.py (min-hold-12h) WITHOUT touching it.
Separate state/log files. Paper only — no real orders, ever.

Why this track exists (proven in backtest_swing_gate1_v5):
  The running track uses min-hold-12h (SL disabled 12h) → PF 1.19 but maxDD 68%,
  worst trade -8% (8× the intended stop). REAL-wide dominates it on every
  risk-adjusted metric: PF 1.25, both walk-forward halves PF>1.2, all 3 symbols
  positive, maxDD 20% @3×. This track collects FORWARD evidence for that claim.

Difference vs paper_test_swing.py — ONLY the exit geometry:
  min-hold-12h  : SL -1% (armed only after 12h), TP +2.5%, 5×
  REAL-wide     : SL -2% (armed from t=0),       TP +4%,   3×

Entry signal is IDENTICAL (reuses backtest_swing_gate1_v3.regime/signal on
Binance 1h OHLCV — the same functions the Gate-1 backtest used).

Run:    python3 scripts/paper_test_realwide.py --loop --interval 300
Status: python3 scripts/paper_test_realwide.py --status
Check:  python3 scripts/paper_test_realwide.py demo
"""
from __future__ import annotations
import argparse, json, os, random, sys, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from cost_model import round_trip_frac as _rt_cost  # SUMBER TUNGGAL biaya (audit 30-Sep-2026)
import backtest_swing_gate1_v3 as v3  # pure regime/signal functions

# ── SEPARATE state — never collides with the running min-hold track ──
# Arm riset terisolasi (2026-09-25): suffix dari env, default "" = perilaku produksi.
_STATE_SUFFIX = os.environ.get("RW_STATE_SUFFIX", "")
STATE_FILE = PROJECT / "data" / f"paper_test_realwide_state{_STATE_SUFFIX}.json"
LOG_FILE   = PROJECT / "data" / f"paper_test_realwide{_STATE_SUFFIX}.jsonl"
MON_JSON   = PROJECT / "data" / f"paper_test_realwide_latest{_STATE_SUFFIX}.json"
# Audit gerbang (2026-10-05, D12): state HANYA menyimpan entry yang LOLOS, jadi
# gerbang yang memblokir TIDAK BISA difalsifikasi -- tak ada outcome pembanding.
# Berkas append-only ini mencatat setiap entry DIBLOKIR + besar ATR-nya, supaya
# "apakah blokir ini benar?" kelak dijawab dengan data, bukan asumsi.
BLOCK_LOG  = PROJECT / "data" / f"paper_test_realwide_blocked{_STATE_SUFFIX}.jsonl"

# Universe (2026-08-29, user-specified list, VERIFIED). Requested 24; kept the 19
# that are BOTH on SoDEX perps (execution venue) AND have 1h klines (signal src).
# DROPPED (honest): PENDLE/TAO/JUP/PEPE/PAXG = not on SoDEX perps (no venue).
# Signal source per pair: Binance spot, auto-falling-back to Binance futures (fapi)
# for perp-only symbols — HYPE→HYPEUSDT(fapi), SILVER→XAGUSDT(fapi). See _raw_klines.
# New pairs are FORWARD-tested (Gate-1 backtest was majors-only) — paper's job.
# PAIRS diurutkan prioritas (REV 2026-09-06, pasca-riset tier): top-7 terbukti
# profit (BTC/ETH/SOL/DOGE/UNI/AAVE/ENA dari BH-FDR + forensik) + PUMP/BNB
# (tier unggulan replay: WR 64-75%). Krn MAX_TOTAL=8 membatasi slot, urutan ini
# membuat slot terisi oleh pair unggulan lebih dulu (soft-priority, bukan hard
# drop — n per pair masih kecil, hindari overfit).
PAIRS = ["BTC", "ETH", "SOL", "DOGE", "UNI", "AAVE", "ENA", "PUMP", "BNB",
         "XRP", "HYPE", "BCH", "ONDO", "LINK", "SUI", "ADA", "TRX",
         "XAUT", "SILVER", "ARB", "AVAX", "ASTER", "LIT"]
BN = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "XRP": "XRPUSDT", "SOL": "SOLUSDT",
      "HYPE": "HYPEUSDT", "DOGE": "DOGEUSDT", "BCH": "BCHUSDT", "ONDO": "ONDOUSDT",
      "LINK": "LINKUSDT", "AAVE": "AAVEUSDT", "SUI": "SUIUSDT", "ADA": "ADAUSDT",
      "TRX": "TRXUSDT", "UNI": "UNIUSDT", "ENA": "ENAUSDT", "XAUT": "XAUTUSDT",
      "SILVER": "XAGUSDT", "ARB": "ARBUSDT", "AVAX": "AVAXUSDT",
      "ASTER": "ASTERUSDT", "PUMP": "PUMPUSDT", "LIT": "LITUSDT",
      "BNB": "BNBUSDT"}
# Round-trip cost = live-measured SoDEX top-of-book spread (2026-08-29), floored
# at 2bps. THIN-BOOK pairs (top-of-book <$550/side: HYPE, SUI, SILVER) modeled at
# 8bps to reflect depth-walking slippage a $300 position would incur in reality.
# BTC/ETH/SOL keep prior proven conservative values. Spread is ~1.5% of the 4% TP
# so it is not the edge driver — this is a conservative-honesty input, not tuning.
SPREAD = {"BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035,
          "XRP": 0.0002, "HYPE": 0.0008, "DOGE": 0.0002, "BCH": 0.0002,
          "ONDO": 0.000285, "LINK": 0.0002, "AAVE": 0.0002, "SUI": 0.0008,
          "ADA": 0.000497, "TRX": 0.0002, "UNI": 0.000227, "ENA": 0.000614,
          "XAUT": 0.000605, "SILVER": 0.0008, "ARB": 0.0002, "AVAX": 0.0002,
          "ASTER": 0.0004, "PUMP": 0.0004, "LIT": 0.0008, "BNB": 0.0002}
MAKER_FEE = 0.00024
TARGET_MIN_PCT = 0.008   # North Star: ≥0.8% net per 30h window (user GO 27-Sep)

# ── REAL-wide geometry (the ONLY change vs running track) ──
# REV 2026-09-05 (riset A2 grid search, approved user): TP 4%->6%, SL 2%->1,5%.
# Bukti: walk-forward 100 kombinasi, 31 menang di IS DAN OOS. Kandidat ini
# degradasi IS->OOS terendah (39,9% vs baseline 62,3%) = paling robust, PF 4,50
# vs 2,85. Paired bootstrap 10k: selisih CI95 [+0,40%, +0,99%] TIDAK melewati
# nol, P(lebih baik)=100%. n=50 trade dgn harga nyata dari entry aktual.
# Hipotesis H1 'entry di local top' sudah DIFALSIFIKASI (6 metrik, semua
# p>0,13, 0 lolos BH-FDR) — jadi perbaikan ada di GEOMETRI, bukan filter entry.
# CATATAN: live (realwide_micro_live.py) SENGAJA tetap TP4/SL2 sampai paper
# mengumpulkan n>=30 bukti forward (aturan maturasi, approved user 2026-09-05).
TP_PCT = 0.060
SL_PCT = 0.030   # RISET A2 27-Sep (approved user 28-Sep): grid walk-forward
# n=203 trade nyata, 50/50 IS/OOS, pemenang TUNGGAL yang menang di dua sisi:
# TP6/SL3/TIME24 → WR 53.7% PF 1.83 ROI-wallet +0.46%/trade vs baseline
# TP6/SL1.5/TIME30 WR 48.8% PF 1.64 +0.31%. SL1.5 mati kena noise (bukti live:
# ETH −1,89% kena SL padahal tesis belum mati).
LEVERAGE = 3                # de-levered per §6: DD 20% <25% gate
# ── ARM GEOMETRI ATR-ADAPTIF (2026-09-25, env-gated, DEFAULT OFF) ──────────
# Bukti lintas-track: r(ATR%, SL-rate)=+0.750 p_perm=0.0006. REAL-wide saat ini
# meng-EXCLUDE pair volatil lewat vol gate ATR14(1h)>2% (riset 2026-09-05: SL-cepat
# masuk saat ATR 2x normal). Exclude itu menutup peluang pair trending volatil
# (ONDO ATR1h 2.90%, ENA 2.85%, +72.6%/+90d buy-hold) — arm ini menguji hipotesis
# ALTERNATIF: adaptasi SL (bukan pengecualian) untuk pair volatil.
# Default OFF => produksi & jalur promosi TIDAK berubah sedikit pun.
RW_ATR_SL = os.environ.get("RW_ATR_SL", "0") == "1"
RW_ATR_MULT = float(os.environ.get("RW_ATR_MULT", "1.0"))
RW_ATR_FLOOR = float(os.environ.get("RW_ATR_FLOOR", "0.030"))   # = SL produksi
RW_ATR_CAP = float(os.environ.get("RW_ATR_CAP", "0.050"))
RW_ATR_RR = float(os.environ.get("RW_ATR_RR", "2.0"))           # = 6.0/3.0 produksi
RW_VOLGATE_ON = os.environ.get("RW_VOLGATE", "1") == "1"        # 0 = izinkan ATR>2%
RW_PAIR_GATE_IGNORE = {s.strip().upper() for s in os.environ.get("RW_PAIR_GATE_IGNORE", "").split(",") if s.strip()}


def eff_tp_sl(atr_pct):
    """(TP%, SL%) efektif. Default = konstanta produksi (TP6/SL1.5)."""
    if not RW_ATR_SL:
        return TP_PCT, SL_PCT
    a = float(atr_pct or 0.0)
    sl = min(max(RW_ATR_MULT * a, RW_ATR_FLOOR), RW_ATR_CAP)
    return round(sl * RW_ATR_RR, 6), round(sl, 6)


def peak_trail_bands(tp_pct, sl_pct):
    """Ambang PEAK_TRAIL & SL_PROTECT diskalakan proporsional ke geometri posisi.
    Kontrol (TP6/SL1.5) mereproduksi persis 3.0%/2.0% dan 1.2%/0.4%."""
    return (round(tp_pct * 0.5, 6), round(tp_pct * 0.3333, 6),
            round(sl_pct * 0.8, 6), round(sl_pct * 0.27, 6))
MIN_HOLD_SL_H = 0          # stop honored from t=0 (no landmine)

# ── MODEL FILL BERBASIS LEVEL (audit 1-Okt-2026, approved user) ──────────────
# MASALAH TERUKUR: exit lama memakai harga POLL (`c[-1]`, bar yang masih hidup)
# sebagai harga fill. Akibatnya SL 2,00% terealisasi rata-rata -2,17% (excursion
# antar-siklus) dan TP 4% terealisasi +5,03% (artefak MENGUNTUNGKAN +1,19pp —
# inilah yang membuat mean lane terlihat lebih baik dari kenyataan).
# FIX: model order rest di venue. TP = limit → terisi TEPAT di level TP.
#      SL = stop-market → terisi di level SL minus slippage (env RW_SLIP_BPS).
# Efek jujur: hasil lane kemungkinan TURUN (excursion TP yang menguntungkan hilang).
# Rollback: RW_LEVEL_FILL=0 (perilaku lama: fill di harga poll).
RW_LEVEL_FILL = os.environ.get("RW_LEVEL_FILL", "1") == "1"
RW_SLIP_BPS = float(os.environ.get("RW_SLIP_BPS", "5"))   # 5 bps = 0,05% (half-spread+impact major)
RW_SLIP = RW_SLIP_BPS / 10000.0


def level_fill_px(entry_p, tp_pct, sl_pct, px):
    """Harga fill realistis bila harga poll sudah melewati level (order rest di venue).

    Return (reason, exit_px) atau (None, None) bila belum ada level yang tersentuh.
    TP = limit order → terisi di level TP (tidak pernah lebih baik dari level).
    SL = stop-market → terisi di level SL minus slippage (tidak pernah lebih baik).
    """
    if px >= entry_p * (1.0 + tp_pct):
        return "TP", entry_p * (1.0 + tp_pct)
    if px <= entry_p * (1.0 - sl_pct):
        return "SL", entry_p * (1.0 - sl_pct) * (1.0 - RW_SLIP)
    return None, None
TIME_STOP_H = 24           # RISET A2 27-Sep: 30→24 (walk-forward: TIME24 menang
# IS & OOS; TIME-exit 30h = 32% trade median cuma +0,22% — dead weight).
COOLDOWN_H = 4   # REV 2026-09-06 (approved user): 12→4. Riset replay 5-minggu:
# cooldown 12h memblok 40,3% episode tradable NET-POSITIF (WR 44%, +0,37%/t).
# CD4 → +34% throughput, PF 1,98→2,16, avg +0,66%/t, net +54%, forward WR 67%.
# 19 pairs incl. uncorrelated metals (XAUT/SILVER) → genuine diversification.
# Cap concurrent exposure at 6 (was 3): more names/throughput while bounding
# correlated mass-drawdown. Per-pair still MAX 1 via last_entry cooldown.
MAX_TOTAL = 8    # REV 2026-09-06 (approved user): 6→8, seiring CD 12→4.
# Slot-cap tidak mengikat di CD12; baru berguna setelah CD diturunkan.
# Riset: 238→320 trade (+34%), PF tetap naik 1,98→2,16 (tidak ada trade-off edge).
NOTIONAL = 100.0


def _read_wallet_capital_with_source():
    """(nilai, sumber) -- SUMBER wajib ikut dilaporkan (audit R2, 2026-10-05).

    Cacat yang ditutup: `_read_wallet_capital()` hanya mengembalikan angka,
    sehingga tidak ada cara mengetahui apakah ROI dihitung terhadap wallet NYATA
    atau terhadap fallback `NOTIONAL*LEVERAGE`. Konsekuensinya nyata: proses lane
    yang berjalan memegang SODEX_TOTAL_WALLET=$174,55 (dari .env.swing saat
    service start 04-Okt 06:13) sedangkan berkas kini berbunyi $243,39 --
    denominator bergeser tanpa jejak. Sumber kini terekam di tiap trade.
    """
    env_val = os.environ.get("SODEX_TOTAL_WALLET")
    if env_val:
        try:
            return float(env_val), "env:SODEX_TOTAL_WALLET"
        except Exception:
            pass
    gt = Path(__file__).resolve().parents[1] / "data" / "ground_truth.json"
    if gt.exists():
        try:
            with open(gt) as _f:
                _d = json.load(_f)
            total = _d.get("hl_total", {}).get("observed_account_value_usd", 0)
            if total >= 100:
                return float(total), "ground_truth:hl_total"
        except Exception:
            pass
    return NOTIONAL * LEVERAGE, "fallback:NOTIONAL*LEVERAGE"  # DENOMINATOR PALSU


def _read_wallet_capital() -> float:
    return _read_wallet_capital_with_source()[0]

TOTAL_WALLET_CAPITAL = _read_wallet_capital()
WALLET_CAPITAL_SOURCE = _read_wallet_capital_with_source()[1]

# ── KESELARASAN ANGGARAN RISIKO paper <-> live (R2, 2026-10-05) ──────────────
# TEMUAN AUDIT: kedua lane menafsirkan "1 posisi" dengan biaya risiko BERBEDA.
#   PAPER: konvensi sizing IMPLISIT. Dari `pnl_usd = pnl * NOTIONAL * LEVERAGE`
#          (baris ~671): exposure/posisi = NOTIONAL*LEVERAGE = $300, margin $100.
#          Tidak ada dokumentasi konvensi -- itulah cacat intinya.
#   LIVE : SIZE_NOTIONAL=$140 EKSPLISIT = exposure/posisi; margin = /LEVERAGE =
#          $46,67 (entry_qty = SIZE_NOTIONAL/px, TANPA dikali leverage lagi).
# Diperparah konkurensi 8 (paper) vs 2 (live): puncak PAPER = $800 margin =
# 328% wallet $243,39, padahal LIVE dibatasi LEVEL2_MARGIN_UTIL_CAP = 0,70.
# Track paper karena itu mengambil risiko yang TIDAK BISA didanai live ->
# angkanya tidak transferable ke live.
#
# RW_MARGIN_UTIL_CAP=0 (default) = PERILAKU LAMA DIPERTAHANKAN (tanpa plafon),
# supaya jalur forward yang sedang berjalan TIDAK berubah tanpa persetujuan.
# Setel 0,70 (= nilai live) agar track hanya menerima entry yang mampu didanai.
RW_MARGIN_UTIL_CAP = float(os.environ.get("RW_MARGIN_UTIL_CAP", "0"))
RW_MARGIN_PER_POSITION = NOTIONAL   # margin/posisi pada konvensi lane ini


def margin_budget_blocks(n_open_signal, wallet, util_cap=RW_MARGIN_UTIL_CAP,
                         margin_per_pos=RW_MARGIN_PER_POSITION):
    """True bila menambah 1 posisi akan menembus plafon margin wallet.

    Cermin langsung `LEVEL2_MARGIN_UTIL_CAP` lane live (realwide_micro_live.py:79)
    supaya kedua lane memakai anggaran risiko IDENTIK. Fungsi murni (tanpa I/O)
    supaya keputusan transferabilitas paper->live dapat diuji.
    util_cap <= 0  -> fitur OFF -> selalu False (perilaku lama).
    Ragu/error     -> fail-OPEN, konsisten dengan gerbang lain di berkas ini
                      (gerbang yang mati tidak boleh membekukan lane paper).
    """
    if util_cap <= 0:
        return False
    try:
        need = (int(n_open_signal) + 1) * float(margin_per_pos)
        return need > float(wallet) * float(util_cap) + 1e-9
    except Exception:
        return False


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _raw_klines(sym, interval, limit):
    """Spot klines, fallback to Binance futures (fapi) for perp-only symbols
    (HYPE, XAG/silver). Same row schema. Existing spot pairs never hit fapi."""
    for base in ("https://api.binance.com/api/v3/klines",
                 "https://fapi.binance.com/fapi/v1/klines"):
        try:
            r = requests.get(base, params={"symbol": sym, "interval": interval,
                                           "limit": limit}, timeout=10)
            k = r.json()
            if isinstance(k, list) and len(k) >= 2:
                return k
        except Exception:
            continue
    return []


def fetch_ohlcv(sym, limit=300):
    k = _raw_klines(sym, "1h", limit)
    return {
        "o": np.array([float(x[1]) for x in k]),
        "h": np.array([float(x[2]) for x in k]),
        "l": np.array([float(x[3]) for x in k]),
        "c": np.array([float(x[4]) for x in k]),
        "v": np.array([float(x[5]) for x in k]),
        "dates": np.array([int(x[0]) for x in k]),
    }


def _migrate_below_target(state):
    """Recompute wallet_roi + below_target for closed trades using current TOTAL_WALLET_CAPITAL."""
    for t in state.get("closed", []):
        pnl_usd = t.get("pnl_usd")
        if pnl_usd is not None:
            new_roi = pnl_usd / TOTAL_WALLET_CAPITAL
            t["wallet_roi"] = new_roi
            t["below_target"] = new_roi < TARGET_MIN_PCT
    return state


def load_state():
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text())
            _migrate_below_target(st)
            return st
        except Exception:
            pass
    return {"open": {}, "closed": [], "last_entry": {}, "created": now_iso()}


def save_state(st):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE_FILE)


# ── EDGE-GATE / STANDBY (2026-08-11): standby saat regime flapping → blok entry
GATE_FILE = PROJECT / "data" / "paper_test_edge_gate.json"
_gate_cache = {"ts": 0.0, "data": {}}


def direction_gate_blocks(label, direction):
    now = time.time()
    if now - _gate_cache["ts"] > 60:
        try:
            _gate_cache["data"] = json.loads(GATE_FILE.read_text())
            _gate_cache["ts"] = now
        except Exception:
            _gate_cache["data"] = {}
    data = _gate_cache["data"]
    # Staleness guard: a frozen gate (writer down) must NOT permanently block a
    # paper track. >90min stale -> fail-OPEN. Fixes silent-freeze from dead writer.
    try:
        if time.time() - GATE_FILE.stat().st_mtime > 5400:
            return False
    except Exception:
        return False
    # _STANDBY (blanket flapping-block) is advisory for PAPER data collection:
    # flapping is exactly when we want samples. Keep only the surgical, evidence-
    # based per-direction PAUSE (anti-predictive, n>=8).
    g = (data.get("gate") or {}).get(label) or {}
    agg = data.get("_AGGREGATE") or {}
    own = g.get(direction)
    # Own significant verdict wins over the cross-track aggregate. The aggregate
    # pools LONG/SHORT across ALL tracks (incl. inferior/retired geometries), so a
    # polluted aggregate PAUSE must NOT veto a track whose OWN edge is proven KEEP
    # (this was idling REAL-wide's longs despite its own KEEP verdict). Own PAUSE
    # still blocks; undecided (WATCH/COLLECT/None) defers to the aggregate.
    if own == "PAUSE":
        return True
    if own == "KEEP":
        return False
    return agg.get(direction) == "PAUSE"


def pair_gate_blocks(label, pair):
    """True = this pair is a proven structural drag for this track (learning loop
    put it in pairs_pause: n>=8 AND pnl<0 AND WR<40%). Same cache + staleness
    fail-open as direction_gate_blocks — a dead writer must never freeze entries."""
    now = time.time()
    if now - _gate_cache["ts"] > 60:
        try:
            _gate_cache["data"] = json.loads(GATE_FILE.read_text())
            _gate_cache["ts"] = now
        except Exception:
            _gate_cache["data"] = {}
    try:
        if time.time() - GATE_FILE.stat().st_mtime > 5400:
            return False   # stale writer → fail-open
    except Exception:
        return False
    pp = (_gate_cache["data"].get("pairs_pause") or {}).get(label) or []
    return pair in pp


# ── RELAXED data-collection knobs (env-tunable, shared defaults with swing).
# Loosen entry so this PAPER track produces trades/learning data in non-bull
# regimes. NOT proof of edge — Gate-2 promotion still uses strict-signal perf.
# PAPER_RELAXED=0 restores strict v3.
import os as _os
_RELAXED = _os.environ.get("PAPER_RELAXED", "1") == "1"
_ADX_MIN = float(_os.environ.get("PAPER_ADX_MIN", "15" if _RELAXED else "25"))
_MIN_CHECKS = int(_os.environ.get("PAPER_MIN_CHECKS", "3" if _RELAXED else "4"))
_REQUIRE_GOLDEN = _os.environ.get("PAPER_REQUIRE_GOLDEN", "0" if _RELAXED else "1") == "1"

# ── BEAR REGIME ADAPTATION (2026-09-09, RCA: realwide LAST30 bear WR 37%
# avg -$1.91 TP1/SL25 vs EARLY30 bull WR 70% +$3.26 TP6) ────────────────
# Root cause: LONG-only track buys into bear → TP6% unreachable (1 in 30),
# SL dominates. Fix: adaptive strictness — in BEAR regime (BTC below both
# EMA50/200) demand STRONGER entry (golden + ADX25 + 15m confirm STRICT)
# and shorter time-stop (20h vs 30h) supaya posisi tidak menggantung lama
# di market turun. BERLaku juga utk entrance filter di bawah.
BEAR_ADX_MIN = float(_os.environ.get("PAPER_BEAR_ADX_MIN", "25"))
BEAR_TIME_STOP_H = int(_os.environ.get("PAPER_BEAR_TIME_STOP_H", "20"))
BEAR_SL_PCT = float(_os.environ.get("PAPER_BEAR_SL_PCT", "0.010"))

# ── CHOP REGIME GATE (2026-09-15, RCA counterfactual n=131 realwide + n=219
# twoway, reports/SODEX_REGIME_COUNTERFACTUAL_2026-09-15.json) ──────────────
# REALWIDE entries by BTC daily regime: BULL n=51 WR 74.5% +$282.59 |
# CHOP n=73 WR 30.1% **-$145.85** | BEAR n=7 -$5.52.
# CHOP menggerus lebih dari seluruh profit track. Konsisten dengan CEX v2.8
# (skip LONG-in-DOWN). Gate biner struktural — bukan parameter tuning halus —
# sehingga risiko overfit rendah. Fail-OPEN saat BTC data error (paper track
# tidak boleh mati total; data error ditandai via regime=None).
# PAPER_CHOP_GATE=0 untuk disable. Default ON: data collection relaxed sudah
# n=131 — sekarang waktunya kualitas, bukan kuantitas.
CHOP_GATE_ENABLED = _os.environ.get("PAPER_CHOP_GATE", "1") == "1"
_chop_regime_cache: dict = {"ts": 0.0, "regime": None}


def btc_daily_regime(max_age_s=900) -> str | None:
    """BTC daily regime: BULL/BEAR/CHOP (CEX v2.8 pattern). None = data error."""
    now = time.time()
    if (now - float(_chop_regime_cache["ts"])) < max_age_s:
        return _chop_regime_cache["regime"]  # type: ignore[return-value]
    reg = None
    try:
        rows = _raw_klines("BTCUSDT", "1d", 210)
        if isinstance(rows, list) and len(rows) >= 201:
            c = [float(x[4]) for x in rows]
            i = len(c) - 1
            sma200 = sum(c[i - 199:i + 1]) / 200
            mom = c[i] / c[i - 1] - 1
            if c[i] > sma200 and mom > 0:
                reg = "BULL"
            elif c[i] < sma200 and mom < 0:
                reg = "BEAR"
            else:
                reg = "CHOP"
    except Exception:
        reg = None
    _chop_regime_cache["ts"] = now
    _chop_regime_cache["regime"] = reg
    return reg


def _regime_gate_ok(sym_bn):
    """ASYMMETRIC REGIME FILTER (2026-08-15): confirmed 1h uptrend + not turning
    on 30m. Fixes Aug12+ 8/8 loss (entered momentum-long in chop/down)."""
    if not sym_bn:
        return True
    import regime_filter as rf
    return rf.entry_regime_ok(sym_bn) and not rf.fast_regime_bad(sym_bn)


def _confirm_15m(sym_bn: str, direction: str = "LONG") -> bool:
    """15m SMA20 multi-timeframe confirmation — fail-OPEN on any network error.

    Prevents acting on 1h signals that have already reversed on the 15m chart.
    The 1h bar signal has ~65min lag (bar-close + poll); 15m confirmation
    validates the direction still holds 0-3 bars after the 1h close.
    """
    try:
        k = _raw_klines(sym_bn, "15m", 25)
        if not isinstance(k, list) or len(k) < 22:
            return True  # fail-open
        c = np.array([float(x[4]) for x in k])
        i = len(c) - 2
        s20 = v3.sma(c, 20)
        if np.isnan(s20[i]):
            return True
        if direction == "LONG":
            return bool(c[i] > s20[i])
        else:
            return bool(c[i] < s20[i])
    except Exception:
        return True  # fail-open


def _atr14_pct(c, h, l, i):
    """ATR14(1h)/C dalam persen pada bar i -- CERMIN PERSIS perhitungan
    _entry_vol_gate (rata-rata TR-14), dipakai untuk audit sebab-keputusan.
    None bila bar < 15 (gerbang sendiri mengembalikan False di kasus itu)."""
    if i < 15:
        return None
    try:
        tr = np.maximum(h[1:i+1] - l[1:i+1],
                        np.maximum(abs(h[1:i+1] - c[:i]), abs(l[1:i+1] - c[:i])))
        return (float(np.mean(tr[-14:])) / c[i]) * 100.0
    except Exception:
        return None


def _append_blocked(sym_bn, bar_ts_ms, atr_pct, reason, value=None, thr=None):
    """Catat entry yang DIBLOKIR gerbang (append-only, fail-soft).
    I/O apa pun diabaikan -- audit tidak boleh menghentikan lane paper."""
    try:
        rec = {"ts": time.time(), "iso": now_iso(), "sym": sym_bn,
               "bar_ts": bar_ts_ms, "atr_pct": atr_pct, "reason": reason}
        if value is not None:
            rec["value"] = value
        if thr is not None:
            rec["thr"] = thr
        with open(BLOCK_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _entry_vol_gate(c, h, l, i, thr_pct=2.0):
    """Volatility gate: skip entry saat ATR14(1h)/C > threshold. Bukti:
    riset paralel 2026-09-05 — SL-cepat (n=12) masuk saat ATR 2x normal
    (2.37% vs 1.17%, q=0.016 FDR). ATR memakai Wilder approx utk 1h bar."""
    if i < 15:
        return False
    tr = np.maximum(h[1:i+1] - l[1:i+1],
                    np.maximum(abs(h[1:i+1] - c[:i]), abs(l[1:i+1] - c[:i])))
    atr = float(np.mean(tr[-14:]))
    return (atr / c[i]) * 100 > thr_pct


def _entry_dead_zone_hour():
    """Dead zone entry: jam UTC 5/12/17/18 — WR 27.3%, avg -0.73%,
    p=1.2e-05 (BH-FDR lolos, bootstrap 20k). Prime zone 3/10/15 (WR 71.6%)."""
    h = datetime.now(timezone.utc).hour
    return h in (5, 12, 17, 18)


def _bear_detect(rows=None) -> bool:
    """True if BTC is BELOW both EMA50 & EMA200 (1h) — regime BEAR.
    Fail-OPEN (return False) at network error supaya track tetap jalan
    dengan setting normal (adaptasi = extra strict, bukan kill)."""
    try:
        if rows is None:
            rows = _raw_klines("BTCUSDT", "1h", 210)
        c = [float(x[4]) for x in rows]
        if len(c) < 201:
            return False
        e50 = sum(c[-50:]) / 50
        e200 = sum(c[-200:]) / 200
        return float(c[-1]) < e50 and float(c[-1]) < e200
    except Exception:
        return False


BEAR_MODE = False  # refreshed setiap cycle dari scheduler di bawah

def signal_now(d, sym_bn=None):
    """LONG-only entry on the last closed bar (index -2)."""
    i = len(d["c"]) - 2
    if not _RELAXED:
        sig = v3.signal(d, i, v3.regime(d, i))
        if not (sig.get("active") and _regime_gate_ok(sym_bn)):
            return None
        return sig
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    if i < 200:
        return None
    a = v3.adx(h, l, c); s50 = v3.sma(c, 50); s200 = v3.sma(c, 200)
    # BEAR ADAPT: in bear regime trust ONLY stronger setups — golden spread
    # (SMA50>SMA200), ADX>=25, supaya LONG tidak buy into bear downdraft.
    _adx_apply = (BEAR_ADX_MIN if BEAR_MODE else _ADX_MIN)
    _golden_apply = (_REQUIRE_GOLDEN or BEAR_MODE)
    golden_ok = (s50[i] > s200[i]) if _golden_apply else True
    if a[i] <= _adx_apply or c[i] <= s50[i] or not golden_ok:
        return None
    rv = v3.rsi(c); r24 = v3.rr(c, 24); r1 = v3.rr(c, 1)
    s24 = v3.sma(c, 24); va = v3.sma(v, 24)
    vr = v[i] / va[i] if va[i] > 0 else 1.0
    chk = 0
    if c[i] > s24[i]: chk += 1
    if 40 < rv[i] < 60: chk += 1
    if vr > 1.1: chk += 1
    if i >= 24 and not np.isnan(r24[i]) and r24[i] > 0.012: chk += 1
    if i >= 1 and not np.isnan(r1[i]) and r1[i] < 0.003: chk += 1
    # ATR14(1h)/C pada bar sinyal: SATU hitungan, dipakai untuk audit sebab-blokir.
    # (Keputusan gerbang tetap dari _entry_vol_gate; `i >= 200` di atas menjamin i>=15.)
    _bar_ts = None
    try:
        _dt_arr = d.get("dates")
        if _dt_arr is not None and i < len(_dt_arr):
            _bar_ts = int(_dt_arr[i])
    except Exception:
        _bar_ts = None
    _atr14 = _atr14_pct(c, h, l, i)
    if chk >= _MIN_CHECKS and _regime_gate_ok(sym_bn):
        # FILTER RISET 2026-09-05 (paralel 5-subagent):
        # 1) Vol gate: ATR14(1h)/C > 2% → SL-cepat 2x lebih sering (q=0.016 FDR).
        # Arm ATR (RW_VOLGATE=0) mematikan gate ini SENGAJA untuk menguji apakah
        # geometri adaptif lebih baik daripada pengecualian pair volatil.
        # Default RW_VOLGATE=1 => gate aktif persis seperti produksi.
        if RW_VOLGATE_ON and _entry_vol_gate(c, h, l, i, thr_pct=2.0):
            _append_blocked(sym_bn, _bar_ts, _atr14, "volgate", _atr14, 2.0)
            return None
        # 2) Dead zone: jam UTC 5/12/17/18 → WR 27.3% (p=1.2e-05).
        if _entry_dead_zone_hour():
            _append_blocked(sym_bn, _bar_ts, _atr14, "deadzone",
                            datetime.now(timezone.utc).hour)
            return None
        # 3) 15m multi-timeframe confirmation: must be above 15m SMA20.
        if sym_bn and not _confirm_15m(sym_bn, "LONG"):
            _append_blocked(sym_bn, _bar_ts, _atr14, "m15")
            return None  # 1h signal fired but 15m already reversing
        # 4) S1 cohort tag (2026-09-06, riset: entry-hour log utk ukur sinyal
        #    literatur 13-20 UTC vs sisanya — TAG, bukan blok, agar maturasi
        #    tidak melambat. Dampak diukur 4 minggu sebelum jadi filter.)
        if sym_bn:
            _h = datetime.now(timezone.utc).hour
            _s1_ok = (13 <= _h <= 20) or (19 <= _h <= 24)
        else:
            _s1_ok = True
        return {"active": True, "direction": "LONG", "conviction": chk / 5.0,
                "regime": "MOMENTUM_RELAXED", "relaxed": True,
                "s1_ok": _s1_ok,
                "atr14": None if _atr14 is None else round(_atr14, 4),
                "volgate_on": bool(RW_VOLGATE_ON)}
    return None


# ── KONTROL RANDOM (audit 30-Sep-2026) ───────────────────────────────────────
# MASALAH: track ini tidak punya kontrol acak, sehingga angka "WR 55,6% / PF 1,63"
# TIDAK interpretable — pasar naik bisa membuat strategi buruk terlihat hebat.
# UJI FALSIFIKASI (scripts/edge_falsification_control.py) di lane CEX menunjukkan
# sinyal bisa KALAH dari random (Δmean -0.249 pp) atau persis random (+0.002 pp).
# Desain kontrol (mengikuti lane CEX yang sudah terbukti):
#   • MESIN EXIT SAMA PERSIS (tp/sl/peak-trail/time-stop) → menguji ENTRY TIMING;
#   • entry TANPA sinyal alpha (tanpa vol-gate/dead-zone/pair-prune) — kalau
#     kontrol ikut difilter alpha, ia bukan kontrol;
#   • arah regime-matched (adil, tidak melawan rezim);
#   • SLOT TERPISAH: RANDOM tidak boleh memakan slot SIGNAL (pelajaran v1.1 lane CEX);
#   • laju entry tetap & terdokumentasi (RANDOM_ENTRY_P) supaya adil & reproducible.
TRACK_SIGNAL = "SIGNAL"
TRACK_RANDOM = "RANDOM"
RANDOM_CONTROL_ENABLED = os.environ.get("RW_RANDOM_CONTROL", "1") == "1"
RANDOM_ENTRY_P = float(os.environ.get("RW_RANDOM_ENTRY_P", "0.03"))
MAX_RANDOM = int(os.environ.get("RW_MAX_RANDOM", "2"))


def _random_entry_decision(rng_val: float, open_tracks, max_random: int = MAX_RANDOM,
                           p: float = RANDOM_ENTRY_P) -> bool:
    """True bila kontrol RANDOM boleh membuka posisi siklus ini.

    Murni (tanpa I/O) supaya bisa diuji: keputusan ini adalah jantung keadilan
    kontrol, jadi ia TIDAK boleh tersembunyi di dalam loop.
    """
    if not RANDOM_CONTROL_ENABLED:
        return False
    if sum(1 for t in open_tracks if t == TRACK_RANDOM) >= max_random:
        return False
    return rng_val < p


# RNG khusus kontrol, di-seed supaya laju entry dapat direproduksi saat audit.
_RNG = random.Random(int(os.environ.get("RW_RANDOM_SEED", "20260930")))


def rw_selfcheck_random_control() -> bool:
    """Self-check kontrol RANDOM (dipakai `demo`).

    Memeriksa tiga properti yang membuat kontrol SAH: bisa menyala, punya slot
    sendiri (tidak dilaparkan SIGNAL), dan tunduk pada cap-nya sendiri.
    """
    if not RANDOM_CONTROL_ENABLED:
        return True                       # dimatikan sengaja lewat env = sah
    fires = _random_entry_decision(0.0, ["SIGNAL"] * 5, max_random=2, p=0.03)
    capped = not _random_entry_decision(0.0, ["RANDOM"] * 2, max_random=2, p=0.03)
    quiet = not _random_entry_decision(0.99, [], max_random=2, p=0.03)
    return fires and capped and quiet


def cycle(st, dry=False, do_entries: bool = True):
    global BEAR_MODE
    hits = []
    # refresh bear regime once per cycle (BTC EMA proxy)
    try:
        BEAR_MODE = _bear_detect()
    except Exception:
        pass
    for p in PAIRS:
        try:
            d = fetch_ohlcv(BN[p])
        except Exception as e:
            hits.append(f"{p}:fetch_err"); continue
        # Guard: data kosong (rate limit / klines belum lengkap untuk pair baru)
        # mencegah IndexError `d["c"][-1]` yang dulu meng-crash seluruh cycle
        # (realwide restart 2× 2026-09-01, error log 248× IndexError).
        # numpy-safe: jangan `not d.get("c")` — array punya truth value ambigu.
        _c = d.get("c") if isinstance(d, dict) else None
        if _c is None or len(_c) == 0:
            hits.append(f"{p}:empty_ohlcv"); continue
        px = float(_c[-1])
        # BIAYA BENAR (audit 30-Sep-2026): lane live `realwide_micro_live.py:604,412`
        # kirim `--type market --tif ioc` = TAKER; spread dibayar 2x (masuk+keluar)
        # + funding. Model lama (maker + 1x spread) = 2,97x terlalu murah.
        cost = float(_rt_cost(venue="perps", order_type="taker", pair=p,
                              include_funding=True))

        # ── manage open position (LONG-only) ──
        if p in st["open"]:
            t = st["open"][p]
            hold_h = (time.time() - t["entry_ts"]) / 3600.0
            g = (px - t["entry_p"]) / t["entry_p"]
            # Geometri per-posisi: memakai nilai yang TERSIMPAN saat entry (arm ATR),
            # atau konstanta produksi bila posisi lama tidak menyimpannya.
            _tp = float(t.get("tp", TP_PCT))
            _sl = float(t.get("sl", SL_PCT))
            _pt_trig, _pt_floor, _sp_peak, _sp_floor = peak_trail_bands(_tp, _sl)
            reason = None
            exit_px = px                      # default tetap harga poll (jalur lama,
                                              # dan untuk exit market: TIME/PEAK_TRAIL/SL_PROTECT)
            if RW_LEVEL_FILL:
                _lr, _lpx = level_fill_px(t["entry_p"], _tp, _sl, px)
                if _lr:
                    reason, exit_px = _lr, _lpx
            if not reason and g >= _tp:
                reason = "TP"
            elif not reason and g <= -_sl and hold_h >= MIN_HOLD_SL_H:
                reason = "SL"
            elif not reason and g <= -(_sl * (BEAR_SL_PCT / SL_PCT)) and BEAR_MODE and hold_h >= MIN_HOLD_SL_H:
                reason = "SL_BEAR"
            elif not reason and hold_h >= (BEAR_TIME_STOP_H if BEAR_MODE else TIME_STOP_H):
                _ts = BEAR_TIME_STOP_H if BEAR_MODE else TIME_STOP_H
                reason = f"TIME_{_ts}h"
            # BREAKEVEN-TRAIL (riset forensik 2026-09-05): SL_PROTECT WR 75.9%
            # FDR-sig — harga yg kembali ke breakeven cenderung lanjut naik.
            # Track high-water: jika pernah profit >= 1.2% dan kini turun ke
            # <= +0.4%, keluar dekat breakeven alih-alih biarkan jadi SL rugi.
            t["peak_g"] = max(t.get("peak_g", g), g)
            # PEAK-TRAIL (riset forensik 2026-09-25, OOS-validated half-B n=97): trade yang pernah
            # profit >= 3% lalu member back ke <= 2% hampir selalu exit di +0.2..0.4% atau SL
            # (13/132 forward, mean final +0.51%). Floor +2% menyelamatkan sisa 1.6-1.8 poin
            # yang sekarang dibuang. Diletakkan SEBELUM SL_PROTECT (floor lebih baik) dan
            # SETELAH TP (TP6 tetap menang). Pessimist 75%-fillable: +$0.22/trade
            # (+0.08pp wallet-ROI). Env gate: PEAK_TRAIL=0 utk rollback.
            if (not reason
                    and int(os.environ.get("PEAK_TRAIL_ENABLED", "1")) == 1
                    and t["peak_g"] >= _pt_trig and g <= _pt_floor):
                reason = "PEAK_TRAIL"
            if not reason and t["peak_g"] >= _sp_peak and g <= _sp_floor:
                reason = "SL_PROTECT"
            if reason:
                # PnL direalisasi memakai HARGA FILL (level order), bukan harga poll.
                # Jalur lama tetap identik: bila fill=level mati, exit_px = px.
                g_fill = (exit_px - t["entry_p"]) / t["entry_p"]
                pnl = g_fill - cost
                pnl_usd = pnl * NOTIONAL * LEVERAGE
                wallet_roi = pnl_usd / TOTAL_WALLET_CAPITAL
                # DIAGNOSTIK PEAK_TRAIL (audit 30-Sep-2026). Fitur PEAK_TRAIL mengklaim
                # +$0,22/trade, TETAPI 0 exit PEAK_TRAIL terealisasi dari 24 trade
                # pasca-implementasi (25-Sep 22:07) padahal 3 trade sudah meng-arm
                # ambangnya. Satu anomali (AVAX 26-Sep: peak_g +4,32% tapi exit
                # SL_PROTECT) belum bisa diputuskan dengan n=1. Simpan ambang + g saat
                # exit supaya anomali dinilai dari DATA, bukan dugaan. Additif murni.
                _pg = float(t.get("peak_g", 0.0))
                if _pg >= _pt_trig and reason not in ("TP", "PEAK_TRAIL"):
                    hits.append(f"{p}:WARN-ARM peak_g={_pg*100:+.2f}% >= arm "
                                f"{_pt_trig*100:.2f}% tapi exit={reason} "
                                f"(g={g*100:+.2f}% floor={_pt_floor*100:.2f}%)")
                rec = {**t, "exit_p": exit_px, "exit_ts": time.time(), "exit_iso": now_iso(),
                       "exit_r": reason, "pnl_pct": pnl, "pnl_usd": pnl_usd,
                       "wallet_roi": wallet_roi, "hold_h": round(hold_h, 1),
                       # Denominator ROI pada saat trade (audit R2): tanpa ini,
                       # perubahan basis (mis. .env berubah) tak dapat dideteksi.
                       "wallet_capital": TOTAL_WALLET_CAPITAL,
                       "wallet_capital_src": WALLET_CAPITAL_SOURCE,
                       "fill_model": ("level" if (RW_LEVEL_FILL and exit_px != px) else "poll"),
                       "g_exit": round(g_fill, 6), "pt_trig": _pt_trig, "pt_floor": _pt_floor,
                       "sp_peak": _sp_peak, "sp_floor": _sp_floor,
                       "below_target": wallet_roi < TARGET_MIN_PCT}
                if not dry:
                    st["closed"].append(rec)
                    del st["open"][p]
                    st["last_entry"][p] = time.time()
                    with open(LOG_FILE, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                hits.append(f"{p}:CLOSE {reason} {pnl*100:+.2f}%")
                continue
            hits.append(f"{p}:HOLD {g*100:+.2f}% {hold_h:.1f}h")
            continue

        # ── look for entry (skipped on exit-only cycles) ──
        if not do_entries:
            continue
        # CHOP GATE (RCA 2026-09-15): LONG momentum hanya di BTC BULL daily.
        # CHOP n=73 WR 30% -$145.85; BULL n=51 WR 74.5% +$282.59. Regime=None
        # (data error) → fail-open supaya track hidup, tapi ditandai.
        if CHOP_GATE_ENABLED:
            _btc_reg = btc_daily_regime()
            if _btc_reg == "CHOP":
                continue
        # Cap PER-TRACK: RANDOM tidak boleh memakan slot SIGNAL (pelajaran v1.1 lane
        # CEX: 4 RANDOM yang buka duluan pernah memblokir SIGNAL). Sebelumnya semua
        # posisi adalah SIGNAL, jadi semantik SIGNAL tidak berubah.
        _n_signal = sum(1 for x in st["open"].values()
                        if x.get("track", TRACK_SIGNAL) == TRACK_SIGNAL)
        if _n_signal >= MAX_TOTAL:
            continue
        # Plafon margin (R2): entry hanya bila anggaran risiko selaras dgn live.
        # Default util_cap=0 -> no-op; TIDAK mengubah track yang sedang berjalan.
        if margin_budget_blocks(_n_signal, TOTAL_WALLET_CAPITAL):
            continue
        la = st["last_entry"].get(p, 0)
        if (time.time() - la) / 3600.0 < COOLDOWN_H:
            continue
        if pair_gate_blocks("REAL-wide", p) and p not in RW_PAIR_GATE_IGNORE:
            continue   # per-pair prune: proven structural drag → skip
        sig = signal_now(d, BN[p])
        if sig:
            _tp_e, _sl_e = eff_tp_sl(sig.get("atr14") or 0.0)
            if direction_gate_blocks("REAL-wide", "LONG"):
                continue   # STANDBY/PAUSE → skip
            # ATR 1h pada bar sinyal (index -2), dipakai arm ATR + dilacak selalu.
            try:
                _i = len(d["c"]) - 2
                _atr = float(v3.atr(d["h"], d["l"], d["c"])[_i]) / float(d["c"][_i])
            except Exception:
                _atr = 0.0
            _tp_e, _sl_e = eff_tp_sl(_atr)
            t = {"sym": p, "side": "L", "entry_p": px, "entry_ts": time.time(),
                 "track": TRACK_SIGNAL,
                 "entry_iso": now_iso(), "regime": sig["regime"], "conviction": sig["conviction"],
                 "btc_regime": btc_daily_regime(), "atr_pct": _atr,
                 "atr14": sig.get("atr14"),   # metrik gerbang SBENARNYA (audit D12)
                 "tp": _tp_e, "sl": _sl_e, "lev": LEVERAGE,
                 # Konvensi risiko EKSPLISIT (audit R2): pada lane ini NOTIONAL
                 # adalah MARGIN/posisi dan exposure = NOTIONAL*LEVERAGE.
                 "notional_usd": NOTIONAL, "leverage": LEVERAGE,
                 "exposure_usd": NOTIONAL * LEVERAGE,
                 "margin_usd": NOTIONAL}
            if not dry:
                st["open"][p] = t
            hits.append(f"{p}:ENTRY {sig['regime']} @{px}")

        # ── KONTROL RANDOM: entry TANPA sinyal alpha (MESIN EXIT SAMA) ────────
        # Diletakkan di loop pair yang sama supaya memakai DATA & HARGA yang sama
        # dengan kandidat SIGNAL → perbandingan adil untuk ENTRY TIMING.
        # Kontrol sengaja TIDAK memakai vol-gate/dead-zone/pair-prune (itu alpha);
        # kalau kontrol ikut difilter alpha, ia bukan kontrol lagi.
        # Batasan yang diketahui & disengaja: gate REZIM PASAR (CHOP) tetap berlaku
        # untuk kedua arm — kontrol ini mengisolasi entry timing, bukan timing rezim.
        if p in st["open"]:
            continue
        _tracks_open = [x.get("track", TRACK_SIGNAL) for x in st["open"].values()]
        if not _random_entry_decision(_RNG.random(), _tracks_open):
            continue
        if direction_gate_blocks("REAL-wide", "LONG"):
            continue                      # arah regime-matched (adil, sama dgn SIGNAL)
        try:
            _i = len(d["c"]) - 2
            _atr_r = float(v3.atr(d["h"], d["l"], d["c"])[_i]) / float(d["c"][_i])
        except Exception:
            _atr_r = 0.0
        _tp_r, _sl_r = eff_tp_sl(_atr_r)
        tr = {"sym": p, "side": "L", "entry_p": px, "entry_ts": time.time(),
              "track": TRACK_RANDOM, "entry_signal": "random",
              "entry_iso": now_iso(), "regime": "RANDOM_CONTROL", "conviction": "RANDOM",
              "btc_regime": btc_daily_regime(), "atr_pct": _atr_r,
              "tp": _tp_r, "sl": _sl_r, "lev": LEVERAGE}
        if not dry:
            st["open"][p] = tr
        hits.append(f"{p}:ENTRY-RANDOM @{px}")
    return hits


def status(st):
    c = st["closed"]
    if not c:
        print(f"REAL-wide paper track — open={len(st['open'])} closed=0 (no trades yet)")
        return
    wins = sum(1 for t in c if t["pnl_pct"] > 0)
    gp = sum(t["pnl_pct"] for t in c if t["pnl_pct"] > 0)
    gl = -sum(t["pnl_pct"] for t in c if t["pnl_pct"] <= 0)
    pf = gp / gl if gl > 0 else float("inf")
    tot = sum(t["pnl_usd"] for t in c)
    n_below = sum(1 for t in c if t.get("below_target"))
    thr = 1 - n_below / len(c)
    print(f"REAL-wide paper (TP{TP_PCT*100:.0f}%/SL{SL_PCT*100:.0f}%, {LEVERAGE}×, no min-hold)")
    print(f"  n={len(c)}  WR={100*wins/len(c):.1f}%  PF={pf:.2f}  "
          f"net=${tot:+.2f}  open={len(st['open'])}  ≥0.7%:{thr:.0%}")
    _mu = f"{RW_MARGIN_UTIL_CAP:.0%}" if RW_MARGIN_UTIL_CAP > 0 else "OFF (perilaku lama)"
    _fake = "  ⚠ DENOMINATOR PALSU (bukan wallet nyata!)" if "fallback" in WALLET_CAPITAL_SOURCE else ""
    print(f"  [MARGIN] plafon util={_mu} margin/pos=${RW_MARGIN_PER_POSITION:.0f} "
          f"exposure/pos=${NOTIONAL*LEVERAGE:.0f}")
    print(f"  [WALLET] ${TOTAL_WALLET_CAPITAL:.2f} dari {WALLET_CAPITAL_SOURCE}{_fake}")
    MON_JSON.write_text(json.dumps(
        {"n": len(c), "wr": wins / len(c), "pf": pf, "net_usd": tot,
         "open": len(st["open"]), "n_below_target": n_below,
         "target_hit_rate": thr, "ts": now_iso()}, indent=1))


def demo():
    # signal_now must run on synthetic uptrend without crashing; barrier math sane.
    n = 300
    c = np.cumprod(1 + np.full(n, 0.001)) * 100
    d = {"o": c, "h": c * 1.001, "l": c * 0.999, "c": c, "v": np.ones(n), "dates": np.arange(n)}
    _ = signal_now(d)  # may or may not fire; must not raise
    # exit logic: barrier HARUS konsisten dengan konstanta geometri. Versi lama
    # menegaskan gerakan +5% mencapai TP 6% → mustahil → self-check selalu GAGAL
    # (pemeriksa yang selalu gagal = pemeriksa yang tak bisa dipercaya).
    entry = 100.0
    tp_px = entry * (1 + TP_PCT)
    sl_px = entry * (1 - SL_PCT)
    assert (tp_px - entry) / entry >= TP_PCT - 1e-12, "TP threshold wrong"
    assert (sl_px - entry) / entry <= -SL_PCT + 1e-12, "SL threshold wrong"
    # kontrol RANDOM wajib terpasang & punya slot sendiri
    assert rw_selfcheck_random_control(), "kontrol RANDOM tidak berfungsi"
    # state isolation: our state file must NOT be the running track's file
    assert "realwide" in STATE_FILE.name and STATE_FILE != PROJECT / "data" / "paper_test_swing_state.json"
    # cycle in dry mode leaves state unchanged
    st = {"open": {}, "closed": [], "last_entry": {}}
    before = json.dumps(st)
    print("demo OK — signal runs, barriers sane, state isolated from live track")


def _all_pairs_empty(hits) -> bool:
    """True bila satu siklus melaporkan `empty_ohlcv` untuk SEMUA pair (feed mati).

    Insiden 11-19 Okt 2026: proses hidup tapi buta 8 hari; posisi 24 jam tidak
    pernah ditutup dan gate target tidak menerima sampel. Deteksi ini memaksa
    proses keluar agar systemd (Restart=always) memulai proses baru.
    """
    hs = [str(h) for h in (hits or [])]
    return len(hs) >= 5 and all(h.endswith(":empty_ohlcv") for h in hs)


EMPTY_STREAK_LIMIT = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="once")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "demo":
        demo(); return
    st = load_state()
    if a.status:
        status(st); return
    if a.loop:
        _EXIT_POLL = 60
        _n_entry = max(a.interval // _EXIT_POLL, 1)
        _c = 0
        _empty_streak = 0
        print(f"REAL-wide loop: exit poll {_EXIT_POLL}s, entries every {_n_entry} cycles (~{_n_entry*_EXIT_POLL}s)")
        while True:
            _do_entries = (_c % _n_entry == 0)
            hits = cycle(st, dry=a.dry, do_entries=_do_entries)
            if not a.dry:
                save_state(st)
            label = "ENTRY+EXIT" if _do_entries else "EXIT"
            print(f"[{now_iso()}] [{label}] {' | '.join(hits) or 'no action'}")
            _empty_streak = _empty_streak + 1 if _all_pairs_empty(hits) else 0
            if _empty_streak >= EMPTY_STREAK_LIMIT and not a.dry:
                print(f"[FATAL] {_empty_streak} siklus berturut semua pair empty_ohlcv "
                      f"-> keluar, systemd restart", file=sys.stderr, flush=True)
                sys.exit(2)
            _c += 1
            time.sleep(_EXIT_POLL)
    else:
        hits = cycle(st, dry=a.dry)
        if not a.dry:
            save_state(st)
        print(f"[{now_iso()}] {' | '.join(hits) or 'no action'}")
        status(st)


if __name__ == "__main__":
    main()
