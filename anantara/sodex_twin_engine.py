#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 SODEX TWIN-ENGINE v2.0 — Implementasi MASTERPLAN FABLE v2 (11 Jun 2026)
 Untuk : Mas Anas — Anantara Sakti Project
 Lisensi: penggunaan pribadi
================================================================================

ARSITEKTUR (sesuai dokumen MASTERPLAN v2):
  ENGINE-1  PEPE Flywheel  : spot MM dua-sisi, size/level/jeda acak,
                             hedge delta via PEPE-PERP (opsional), biaya negatif.
  ENGINE-2  Perps Stack    : maker churn BTC-PERP (+ slot cash-and-carry),
                             kapasitas DIKUNCI oleh TreasuryRule.
  TREASURY RULE (G6)       : Engine-2 hanya membakar profit terealisasi
                             Engine-1; modal pokok maks $30 (kalibrasi mgg-1).
  GATES G0..G6             : startup check, kalibrasi Selasa, ramp harian,
                             dilusi mingguan, hard-stop, rebate push, subsidi.
  LEDGER (SQLite)          : semua fill, fee, bucket (S/P/CC), RT, ekuitas.
  YIELD TRACKER            : laporan Selasa -> vol/poin, biaya per 1.000 poin.
  MAKER-SHARE ESTIMATOR    : offline, dari file trades collector Anda.

KEAMANAN (defense-in-depth):
  * TIDAK ADA kredensial di kode. Semua via environment / file .env (chmod 600).
  * DRY_RUN adalah DEFAULT. Mode live butuh: --live  +  env CONFIRM_LIVE=YES
    + konfirmasi ketik manual di terminal. Tiga kunci terpisah.
  * Hard caps independen dari logika strategi (inventori, notional, loss harian,
    drawdown 15%, fee-dari-pokok $30). Guard menang atas strategi, selalu.
  * subprocess shell=False + whitelist argumen (anti command-injection).
  * Log redaction: API key/secret/token tidak pernah tertulis ke log.
  * Tanpa eval/exec/pickle; parsing hanya JSON; SQLite parameterized query
    (anti SQL-injection); file state ditulis atomik.
  * SIGINT/SIGTERM -> cancel semua order, flush ledger, keluar bersih.
  * Integritas: SHA-256 file dicetak saat start (pin versi yang Anda audit).

CARA PAKAI:
  python3 sodex_twin_engine.py selftest          # uji penuh di simulator
  python3 sodex_twin_engine.py run               # dry-run (paper) default
  python3 sodex_twin_engine.py run --live        # live (3 kunci di atas)
  python3 sodex_twin_engine.py report            # input poin Selasa -> G1/G3
  python3 sodex_twin_engine.py estimate-share trades.jsonl   # gerbang G5
  python3 sodex_twin_engine.py status            # ringkasan ledger & gates

INTEGRASI (satu-satunya bagian yang perlu Anda sambungkan):
  Kelas `SodexLiveAdapter` di bawah berisi TODO yang memetakan setiap method
  ke client SoDEX Anda yang sudah ada (`bin/sodex` / modul REST Anda).
  Seluruh strategi, guard, gate, treasury, dan ledger TIDAK perlu diubah.

Dependensi: HANYA pustaka standar Python 3.10+ (tanpa pip, tanpa supply-chain
risk). Telegram memakai urllib stdlib.
================================================================================
"""

from __future__ import annotations

import argparse
import math
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from secrets import SystemRandom

getcontext().prec = 28
RNG = SystemRandom()          # CSPRNG: jitter non-deterministik & tak bisa diprediksi
UTC = timezone.utc
D = Decimal
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SAFETY_HALT_FILE = DATA_DIR / "SAFETY_HALT"
SPOT_SELL_VERIFIED_FILE = DATA_DIR / "SPOT_SELL_VERIFIED"


def _data_payload(payload):
    """Return SoDEX API data object, accepting raw or {data: ...} envelopes."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def write_safety_halt(reason: str, **extra) -> Path:
    """Fail-closed live-order halt marker; never contains credentials.

    IDEMPOTEN (audit 29-Sep-2026): bila penanda sudah ADA, JANGAN ditimpa. Alasan
    pertama (yang paling awal, mis. 'drawdown') harus tetap utuh untuk diagnosis
    operator; menimpanya dengan alasan turunan (mis. 'live_start_blocked:...')
    justru menyesatkan. Penanda = gerbang keberadaan, bukan log.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SAFETY_HALT_FILE.exists():
        return SAFETY_HALT_FILE
    payload = {"ts": datetime.now(UTC).isoformat(), "reason": str(reason),
               "source": "sodex_twin_engine", **extra}
    SAFETY_HALT_FILE.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    try:
        SAFETY_HALT_FILE.chmod(0o600)
    except OSError:
        pass
    return SAFETY_HALT_FILE


def e1_spot_capability_block_reason() -> str | None:
    """Return reason to block E1 spot sells until capability proof exists."""
    return None if SPOT_SELL_VERIFIED_FILE.exists() else "spot_sell_capability_unverified"


# ── REGIME-ADAPTIVE HEDGE (2026-06-22) ─────────────────────────────────────────
# Solusi PR-terbesar user: deteksi regime (tren persisten) → bull=unhedged (E1 bagus),
# bear=delta-neutral hedge (lindungi). BUKAN prediksi gaib — deteksi tren yg persisten
# (autokorelasi multi-jam), menangkap mayoritas bear panjang dgn lag kecil.
# Peta hedge: spot pair → (perp, contract_multiplier). 1000PEPE/1000SHIB = 1000 coin/kontrak.
HEDGE_MAP = {
    "PEPE/USDC": ("1000PEPE-USD", 1000),
    "SHIB/USDC": ("1000SHIB-USD", 1000),
    "XLM/USDC":  ("XLM-USD", 1),
    "DOGE/USDC": ("DOGE-USD", 1),
    "ADA/USDC":  ("ADA-USD", 1),
    "SOL/USDC":  ("SOL-USD", 1),
}


def hedge_qty_for_inventory(spot_inv_qty: Decimal, contract_mult: int) -> Decimal:
    """Qty perp short utk hedge inventory spot. 1000PEPE-USD: 1 kontrak = 1000 PEPE,
    jadi hedge X PEPE = short X/1000 kontrak. KRITIS: salah konversi = hedge salah ukuran."""
    if contract_mult <= 0:
        return D(0)
    return spot_inv_qty / D(contract_mult)


class RegimeDetector:
    """Deteksi regime tren per-coin dari sampel harga (persisten, bukan tick-predict).

    Sampel di-throttle (~1 per sample_interval detik), simpan window jam-an. Regime:
      BULL  : harga > SMA × (1 + thr)  → uptrend → E1 unhedged (nikmati upside)
      BEAR  : harga < SMA × (1 - thr)  → downtrend → aktifkan hedge (lindungi)
      NEUTRAL: di antara → choppy → hedge parsial
    Lag = beberapa sampel (jam), trade-off deteksi vs whipsaw (thr meredam noise).
    """
    def __init__(self, window: int = 36, sample_interval_s: int = 300,
                 bull_thr: float = 0.004, bear_thr: float = 0.004):
        self.window = window
        self.sample_interval_s = sample_interval_s
        self.bull_thr = bull_thr
        self.bear_thr = bear_thr
        self._samples: list[float] = []
        self._last_ts: float = 0.0

    def update(self, price: float, now: float) -> None:
        if price <= 0:
            return
        if now - self._last_ts < self.sample_interval_s:
            return
        self._last_ts = now
        self._samples.append(price)
        if len(self._samples) > self.window:
            self._samples.pop(0)

    def regime(self) -> str:
        n = len(self._samples)
        if n < max(4, self.window // 3):
            return "NEUTRAL"  # data belum cukup → aman (tak agresif)
        sma = sum(self._samples) / n
        cur = self._samples[-1]
        if sma <= 0:
            return "NEUTRAL"
        dev = (cur - sma) / sma
        if dev > self.bull_thr:
            return "BULL"
        if dev < -self.bear_thr:
            return "BEAR"
        return "NEUTRAL"

    def hedge_ratio(self) -> Decimal:
        """Fraksi inventory yg di-hedge berdasar regime: BEAR=1 (penuh), NEUTRAL=0.5,
        BULL=0 (tanpa hedge, nikmati upside)."""
        r = self.regime()
        return {"BEAR": D("1.0"), "NEUTRAL": D("0.5"), "BULL": D("0.0")}[r]


# ── INTEGRASI EKOSISTEM ANANTARA: Intelligence + Pre-Sentiment (sinyal LEADING) ──
# Daemon menulis composite intelligence + Pre-Sentiment forecast tiap jam ke
# intel_YYYYMMDD.jsonl. Engine baca → deteksi arah LEBIH DINI (leading) drpd trend
# filter (lagging). Inilah saran user: manfaatkan Intelligence + Pre-Sentiment +
# Pre-Gain systems yg sudah ber-edge terbukti.
_INTEL_DIR = str(Path(__file__).resolve().parent.parent /
                 "freqtrade_user_data" / "data" / "binance" / "intelligence")


def read_intel_signal(intel_dir: str = _INTEL_DIR, max_age_min: float = 90.0) -> dict | None:
    """Baca sinyal Intelligence+Pre-Sentiment terbaru dari cache daemon.
    Returns {score, btc_dir, btc_conf, event_risk, age_min} atau None bila stale/absent.
    Fail-safe: None → engine pakai trend filter sendiri (tak bergantung daemon)."""
    import glob
    try:
        files = sorted(glob.glob(os.path.join(intel_dir, "intel_*.jsonl")))
        if not files:
            return None
        last_line = None
        for ln in open(files[-1]):
            if ln.strip():
                last_line = ln
        if not last_line:
            return None
        d = json.loads(last_line)
        age = (time.time() - float(d.get("ts", 0))) / 60.0
        if age > max_age_min:
            return None  # stale → jangan pakai (fail-safe ke trend)
        return {
            "score": float(d.get("composite_score", 50.0)),
            "btc_dir": int(d.get("fc_BTC_dir_enc", 1)),   # 0=DOWN,1=NEUTRAL,2=UP (lazim)
            "btc_conf": float(d.get("fc_BTC_conf", 0.0)),
            "event_risk": str(d.get("event_risk_level", "")),
            "age_min": round(age, 1),
        }
    except Exception:
        return None


def intel_regime(sig: dict | None) -> str | None:
    """Map sinyal intelligence → regime LEADING. None bila tak ada sinyal (fallback trend).
    Score ≥55 = BULL, ≤45 = BEAR. Event RED + score lemah → condong BEAR (defensif)."""
    if not sig:
        return None
    score = sig["score"]
    red = sig.get("event_risk") == "RED"
    if score >= 55:
        return "BULL"
    if score <= 45 or (red and score < 50):
        return "BEAR"
    return "NEUTRAL"


def combined_regime(trend_regime: str, intel: str | None) -> str:
    """Gabung sinyal LEADING (intel) + LAGGING (trend). Intel prioritas (lebih dini)
    saat tersedia; trend sbg konfirmasi/fallback. Bila keduanya ada & SETUJU → kuat.
    Bila intel BEAR → BEAR (defensif lebih awal, sesuai tujuan user). Bila intel None
    → pakai trend murni."""
    if intel is None:
        return trend_regime           # daemon stale → andalkan trend sendiri
    if intel == "BEAR" or trend_regime == "BEAR":
        return "BEAR"                 # salah satu bearish → defensif (lindungi modal)
    if intel == "BULL" and trend_regime in ("BULL", "NEUTRAL"):
        return "BULL"                 # intel bullish + trend tak melawan → nikmati upside
    return "NEUTRAL"

# ── SIGALRM handler: convert to exception for step timeout ──
class StepTimeout(Exception):
    pass

def _alarm_handler(signum, frame):
    raise StepTimeout("step timeout — signal.alarm triggered")

signal.signal(signal.SIGALRM, _alarm_handler)

# ============================== 1. KONFIGURASI ===============================

def _env(name: str, default: str = "") -> str:
    """Baca env + buang komentar inline.

    AUDIT 29-Sep-2026 (akar restart-loop 138×): systemd EnvironmentFile TIDAK memotong
    komentar inline → `TE_DRAWDOWN_STOP=0.06   # align $15 cap` terbaca apa adanya →
    _env_dec() → SystemExit("CONFIG ERROR: ... bukan angka valid") → engine MATI saat
    start → watchdog restart → loop. Engine tak bisa hidup sama sekali karena ini.
    Fix: potong dari ' #' pertama. Aman untuk nilai config (tak ada '#' di dalam nilai).
    """
    raw = os.environ.get(name, default)
    # Kasus A: nilai SELURUHNYA komentar, mis. `TE_SPOT_PAIR_2=   # 29-Sep: DI-DISABLE...`.
    # systemd EnvironmentFile membuang spasi awal → raw = "# 29-Sep: ..." (mulai '#',
    # tanpa ' #') sehingga cek di bawah TIDAK kena. Nilai seperti ini bermakna "kosong/
    # dinonaktifkan" — kalau tidak ditangani, teks komentar jadi "symbol" → engine
    # mencoba mengaktifkan pair palsu → "symbol not active" + single-pair mode.
    if raw.strip().startswith("#"):
        return ""
    # Kasus B: komentar inline setelah nilai, mis. `TE_DRAWDOWN_STOP=0.06   # align $15`.
    if " #" in raw:
        raw = raw.split(" #", 1)[0]
    return raw.strip()

def _env_dec(name: str, default: str) -> Decimal:
    raw = _env(name, default)
    try:
        v = D(raw)
    except Exception:
        raise SystemExit(f"CONFIG ERROR: {name}='{raw}' bukan angka valid")
    return v

@dataclass(frozen=True)
class Config:
    # --- identitas pasar (format SoDEX: PEPE/USDC spot, BTC-USD perps) ---
    spot_pair:  str = _env("TE_SPOT_PAIR",  "PEPE/USDC")
    spot_pair_2: str = _env("TE_SPOT_PAIR_2", "SHIB/USDC")  # pair kedua — default SHIB
    spot_pair_3: str = _env("TE_SPOT_PAIR_3", "")  # Jun 17: disabled — tight spread, no SOL balance
    spot_pair_4: str = _env("TE_SPOT_PAIR_4", "")  # Jun 17: disabled — tight spread, no XLM balance
    hedge_perp: str = _env("TE_HEDGE_PERP", "PEPE-USD")
    churn_perp: str = _env("TE_CHURN_PERP", "ENA-USD")  # Jun 17: 0.113% spread, $14K depth — PROFITABLE
    churn_perp_2: str = _env("TE_CHURN_PERP_2", "XPL-USD")  # Jun 17: 0.107% spread, $22K depth
    churn_perp_3: str = _env("TE_CHURN_PERP_3", "TON-USD")  # Jun 17: 0.213% spread, 395 qty

    # --- fee EFEKTIF (Tier-0 x diskon staking 10% Anda) ---
    spot_maker_fee: Decimal = _env_dec("TE_SPOT_MAKER_FEE", "0.000315")
    perp_maker_fee: Decimal = _env_dec("TE_PERP_MAKER_FEE", "0.000108")
    # B20: taker fee perps (dipakai E2Dir — order direksional = IOC/taker)
    # Tier-0 SoDEX: taker 0.020% = 0.0002 (vs maker 0.0108% = 0.000108)
    perp_taker_fee: Decimal = _env_dec("TE_PERP_TAKER_FEE", "0.0002")

    # --- modal & hard caps (MASTERPLAN Bag.7 & guard R-series) ---
    capital_usd:        Decimal = _env_dec("TE_CAPITAL_USD", "60")
    principal_fee_cap:  Decimal = _env_dec("TE_PRINCIPAL_FEE_CAP", "30")   # G4
    max_inventory_usd:  Decimal = _env_dec("TE_MAX_INVENTORY_USD", "60")   # tanpa hedge
    max_inventory_hdg:  Decimal = _env_dec("TE_MAX_INVENTORY_HEDGED", "180")
    max_open_notional:  Decimal = _env_dec("TE_MAX_OPEN_NOTIONAL", "600")
    daily_loss_limit:   Decimal = _env_dec("TE_DAILY_LOSS_LIMIT", "10")    # USD
    drawdown_stop_frac: Decimal = _env_dec("TE_DRAWDOWN_STOP", "0.15")     # 15%

    # --- Engine-1 Flywheel ---
    # DEFAULT $10-15-20/RT: calibrated for $60 capital.
    # Exchange rejects spot BUY orders > available USDC balance.
    # With $60, a $150 order is ALWAYS rejected → zero fills → zero RT profit.
    # $10-15-20 keeps max exposure at ~$20 (1/3 of capital) per quote.
    # Override: TE_E1_SIZE_LADDER env var (e.g. "20,30,40" for $120+ capital).
    e1_size_ladder: tuple = tuple(
        D(x.strip()) for x in _env("TE_E1_SIZE_LADDER", "10,15,20").split(",") if x.strip()
    ) or (D("10"), D("15"), D("20"))
    e1_min_spread:  Decimal = _env_dec("TE_E1_MIN_SPREAD", "0.0025")  # profit focus — wider spread = more profit per RT
    e1_pair2_min_spread: Decimal = _env_dec(
        "TE_E1_PAIR2_MIN_SPREAD", "0.0015")  # B48: SHIB ~0.21% spread < e1_min_spread 0.25%
    e1_min_net_rt:  Decimal = _env_dec("TE_E1_MIN_NET_RT", "0.0008")  # G2: +0.08%/RT
    # B14: gate profitabilitas keras (pakai akunting jujur B13). Pause quoting bila
    # net rate jujur < pause_floor atas ≥ gate_min_n RT; resume bila > resume_floor
    # (histeresis cegah flapping). Doktrin: tidak farming pada EV negatif.
    e1_pause_floor:  Decimal = _env_dec("TE_E1_PAUSE_FLOOR", "-0.0005")  # -0.05%/RT
    e1_resume_floor: Decimal = _env_dec("TE_E1_RESUME_FLOOR", "0.0002")  # +0.02%/RT
    e1_gate_min_n:   int = int(_env("TE_E1_GATE_MIN_N", "20"))
    # B19: EKSPERIMEN BER-BUDGET (uji hipotesis "quote hanya saat spread lebar").
    # OFF default — aktifkan via TE_E1_RESEARCH=1 SETELAH persetujuan budget.
    # Saat aktif: override pause B14, quote HANYA saat spread ≥ research_min_spread,
    # auto-HALT bila rugi jujur ≥ research_budget ATAU n RT ≥ research_target_n.
    e1_research_enabled:    bool = _env("TE_E1_RESEARCH", "0") == "1"
    e1_research_min_spread: Decimal = _env_dec("TE_E1_RESEARCH_MIN_SPREAD", "0.005")  # 50 bps
    e1_research_budget:     Decimal = _env_dec("TE_E1_RESEARCH_BUDGET", "3.0")  # maks rugi $3
    e1_research_target_n:   int = int(_env("TE_E1_RESEARCH_N", "100"))  # auto-stop n RT
    e1_quote_ttl_s: tuple = (10, 25)
    e1_hedge_band:  Decimal = _env_dec("TE_E1_HEDGE_BAND", "25")      # USD delta sblm hedge
    # --- REGIME-ADAPTIVE HEDGE (2026-06-22) — solusi PR-terbesar user ---
    # bull=unhedged (nikmati upside), bear=delta-neutral hedge (lindungi). Regime dari
    # Intelligence+Pre-Sentiment (leading) + trend (fallback). Staged: hedge_pairs="" = semua.
    e1_hedge_enabled: bool = _env("TE_E1_HEDGE_ENABLED", "0") == "1"   # default OFF (opt-in)
    e1_hedge_pairs:   str  = _env("TE_E1_HEDGE_PAIRS", "")             # staged rollout; "" = semua
    e1_regime_window: int  = int(_env("TE_E1_REGIME_WINDOW", "36"))    # sampel tren
    e1_regime_thr:    Decimal = _env_dec("TE_E1_REGIME_THR", "0.004")  # ambang BULL/BEAR vs SMA
    # --- Fase 1: perbaikan inventori (Fable §3.3) ---
    e1_inv_cap_per_pair:  Decimal = _env_dec("TE_E1_INV_CAP", "20")   # cap per pair: ~1/3 of $60 capital
    e1_inv_skew_frac:     Decimal = _env_dec("TE_E1_SKEW_FRAC", "0.50") # skew quote saat inv > 50% cap
    e1_inv_flush_minutes: int = 30                                         # jual paksa setelah X menit
    e1_force_flat_eod:    bool = True                                      # flat tiap akhir sesi
    e1_bad_hours: tuple = tuple(
        int(x.strip()) for x in _env("TE_E1_BAD_HOURS", "").split(",") if x.strip().lstrip('-').isdigit()
    ) or ()  # Jun 16: DISABLED — no bad hours for max volume

    # --- Engine-2 ---
    e2_enabled: bool = _env("TE_E2_ENABLED", "0") == "1"  # Jun 17: DISABLED — perps ghost bug, unreliable PnL tracking
    # B55: clip E2 kini bisa di-override via env (TE_E2_CLIP_MIN/MAX). Default lama
    # $100-200 BERBAHAYA saat margin perps kecil (mis. $52): leg2 gagal → posisi
    # nyangkut + margin call. Untuk uji ilmiah pakai clip kecil ($12-20).
    e2_clip_usd: tuple = (_env_dec("TE_E2_CLIP_MIN", "100"), _env_dec("TE_E2_CLIP_MAX", "200"))
    # B57: timeout fill E2 configurable. Default lama (30,120)s → churn blocking
    # lambat (1 RT/menit). Pendek (mis. 5,12) → cycle cepat, mirip re-quote E1.
    e2_fill_timeout_s: tuple = (int(_env("TE_E2_FILL_TMO_MIN", "30")),
                                int(_env("TE_E2_FILL_TMO_MAX", "120")))
    # B57: frekuensi panggil churn E2 (tiap N iterasi orchestrator). Kecil=lebih sering.
    e2_call_every: int = int(_env("TE_E2_CALL_EVERY", "3"))
    e2_est_cost_rate: Decimal = _env_dec("TE_E2_EST_COST", "0.00030")  # fee+adverse, konservatif
    # B56: offset maker E2 dari touch (dalam kelipatan spread/tick) agar tidak
    # menyilang di 1-tick perps. 1.0 = 1 tick inside-favor (default aman).
    e2_maker_tick_offset: Decimal = _env_dec("TE_E2_MAKER_TICK_OFFSET", "1.0")
    e2_pair_max_failures: int = int(_env("TE_E2_PAIR_MAX_FAILURES", "3"))
    e2_pair_cooldown_s: int = int(_env("TE_E2_PAIR_COOLDOWN_S", "900"))
    e2_route_max_failures: int = int(_env("TE_E2_ROUTE_MAX_FAILURES", "3"))
    e2_route_fail_window_s: int = int(_env("TE_E2_ROUTE_FAIL_WINDOW_S", "600"))
    e2_route_cooldown_s: int = int(_env("TE_E2_ROUTE_COOLDOWN_S", "3600"))

    # --- Phase 2: Engine-2 Directional (sinyal arah funding+OBI) ---
    # OFF default: paper-first, micro-budget. Aktifkan: TE_E2_DIR_ENABLED=1
    e2_dir_enabled:            bool    = _env("TE_E2_DIR_ENABLED", "0") == "1"
    # B23: pair="" → scan dinamis semua 78 pair SoDEX perps, pilih |funding| tertinggi.
    # Lebih efektif dari hardcode ENA-USD yang fundingnya flat (0.0013%/8h).
    e2_dir_pair:               str     = _env("TE_E2_DIR_PAIR", "")   # "" = scan dinamis
    e2_dir_size_usd:           Decimal = _env_dec("TE_E2_DIR_SIZE", "5.0")   # NOTIONAL/RT (bukan margin)
    # LEVERAGE = pengganda volume (compendium §2.2). Margin = notional/leverage.
    # 20x: $25 margin → $500 posisi → $1000/RT vol → 1300 RT/mgg = $1.3M target.
    # Mulai 10x (aman), ramp 20x saat WR & ratio terbukti. SL ketat wajib (likuidasi).
    e2_dir_leverage:           int     = int(_env("TE_E2_DIR_LEVERAGE", "1"))
    e2_dir_sl_pct:             Decimal = _env_dec("TE_E2_DIR_SL", "0.01")    # 1% stop-loss
    e2_dir_tp_pct:             Decimal = _env_dec("TE_E2_DIR_TP", "0.02")    # 2% take-profit (R:R=2:1)
    e2_dir_hold_s:             int     = int(_env("TE_E2_DIR_HOLD_S", "1800"))  # 30 mnt timeout
    e2_dir_budget:             Decimal = _env_dec("TE_E2_DIR_BUDGET", "10.0")   # cap rugi $10 keras
    e2_dir_min_n:              int     = int(_env("TE_E2_DIR_MIN_N", "30"))   # min RT utk edge gate
    # B23: threshold dikalibrasi untuk skala SoDEX (bukan Binance/HL).
    # SoDEX max funding ~0.008%/8h; threshold lama 0.05%/8h TIDAK PERNAH tercapai (n=78 survey).
    # Default baru: 0.003%/8h — ambil pair dengan funding ≥ 3× modus SoDEX (modus=0.0013%/8h).
    e2_dir_funding_thr:        Decimal = _env_dec("TE_E2_DIR_FUNDING_THR", "0.00003")  # 0.003%/8h
    e2_dir_obi_thr:            Decimal = _env_dec("TE_E2_DIR_OBI_THR", "0.15")  # imbalance ≥15%
    e2_dir_live_enabled:       bool    = _env("TE_E2_DIR_LIVE", "0") == "1"  # paper default, LIVE butuh flag

    # --- E2 MOMENTUM (high-frequency signal layer, 2026-06-21) ---
    # Funding-only terlalu jarang (~8 pair). Momentum fires sering di banyak pair likuid
    # → throughput utk volume target. PAPER-FIRST: ukur WR dulu, live butuh flag + WR proven.
    e2_mom_enabled:   bool    = _env("TE_E2_MOM_ENABLED", "0") == "1"
    e2_mom_live:      bool    = _env("TE_E2_MOM_LIVE", "0") == "1"     # paper default
    e2_mom_thr:       Decimal = _env_dec("TE_E2_MOM_THR", "0.0015")    # 0.15% gerak/interval → sinyal
    e2_mom_min_dt:    int     = int(_env("TE_E2_MOM_MIN_DT", "20"))    # detik min antar-observasi
    e2_mom_max_dt:    int     = int(_env("TE_E2_MOM_MAX_DT", "180"))   # detik max (stale)
    e2_mom_min_vol24h: Decimal = _env_dec("TE_E2_MOM_MIN_VOL24H", "100000")  # likuiditas min
    e2_mom_top_n:     int     = int(_env("TE_E2_MOM_TOP_N", "12"))     # pair teratas yg di-scan
    e2_mom_hold_s:    int     = int(_env("TE_E2_MOM_HOLD_S", "120"))   # hold scalp pendek (feedback cepat)

    # --- PRE-GAIN BRIDGE (Top Loser → E2Dir SHORT, BEAR only, 2026-06-22) ---
    # Mengintegrasikan Pre-Gain scan system dgn SoDEX: saat regime BEAR, Top Loser
    # dari HL dipetakan ke SoDEX perps pair → sinyal SHORT ke E2Dir.
    # Intel+Sentiment combined_regime sbg gate: hanya aktif saat BEAR.
    e2_pregain_min_score:  int  = int(_env("TE_E2_PREGAIN_MIN_SCORE", "65"))
    e2_pregain_max_signals: int = int(_env("TE_E2_PREGAIN_MAX_SIGNALS", "3"))
    e2_mom_max_open:  int     = int(_env("TE_E2_MOM_MAX_OPEN", "4"))   # maks posisi paralel
    # FALSIFICATION (2026-06-21): kontinuasi WR=37.5% (n=16) → GUGUR. Flip ke REVERSI
    # (mean-reversion): harga melonjak naik → SELL (balik), turun → BUY. WR komplemen ~62%.
    e2_mom_reversion: bool    = _env("TE_E2_MOM_REVERSION", "1") == "1"  # default reversi (kontinuasi gugur)
    # SIGNAL MODE: "momentum" (harga, noise-dominated) atau "ofi" (order-flow imbalance,
    # flow orderbook — lead prediktif terdokumentasi, Cont-Kukanov-Stoikov 2014).
    e2_sig_mode:      str     = _env("TE_E2_SIG_MODE", "ofi")
    e2_ofi_thr:       Decimal = _env_dec("TE_E2_OFI_THR", "0.25")      # |nOFI| normalisasi → sinyal
    e2_ofi_hold_s:    int     = int(_env("TE_E2_OFI_HOLD_S", "60"))    # hold pendek (OFI lead singkat)

    # --- event guard: ISO-8601 UTC dipisah koma, jeda +/-30 menit ---
    event_guard_utc: str = _env("TE_EVENT_GUARD", "")
    event_guard_pad_min: int = 30

    # --- infra ---
    db_path:   str = _env("TE_DB", "twin_engine.db")
    log_path:  str = _env("TE_LOG", "twin_engine.log")
    monitor_path: str = _env("TE_MONITOR_PATH", "data/twin_monitor.jsonl")   # time-series snapshot
    monitor_latest: str = _env("TE_MONITOR_LATEST", "data/twin_monitor_latest.json")  # snapshot terkini
    spread_path: str = _env("TE_SPREAD_PATH", "data/twin_spread.jsonl")      # B18: sampel spread (riset edge E1)
    tg_token:  str = _env("TELEGRAM_BOT_TOKEN")
    tg_chat:   str = _env("TELEGRAM_CHAT_ID")
    sodex_cli: str = _env("SODEX_CLI", "")        # path absolut bin/sodex Anda (opsional)

    def event_guard_windows(self):
        out = []
        for tok in filter(None, (t.strip() for t in self.event_guard_utc.split(","))):
            try:
                t0 = datetime.fromisoformat(tok).replace(tzinfo=UTC)
                pad = timedelta(minutes=self.event_guard_pad_min)
                out.append((t0 - pad, t0 + pad))
            except ValueError:
                logging.warning("event_guard: token tak valid diabaikan: %r", tok)
        return out

# ============================ 2. LOGGING & REDAKSI ===========================

class RedactFilter(logging.Filter):
    """Pastikan rahasia tidak pernah bocor ke log — termasuk via exception."""
    def __init__(self):
        super().__init__()
        self.secrets = [s for s in (
            _env("SODEX_API_KEY"), _env("SODEX_API_SECRET"),
            _env("TELEGRAM_BOT_TOKEN"),
            _env("SODEX_PRIVATE_KEY"),  # S6 fix (audit 06-Okt-2026): private key EIP-712
        ) if len(s) >= 6]
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for s in self.secrets:
            if s in msg:
                record.msg, record.args = msg.replace(s, "[REDACTED]"), ()
        return True

def setup_logging(cfg: Config):
    fmt = "%(asctime)sZ %(levelname)s %(message)s"
    logging.Formatter.converter = time.gmtime
    h_file = logging.FileHandler(cfg.log_path, encoding="utf-8")
    h_out  = logging.StreamHandler(sys.stdout)
    for h in (h_file, h_out):
        h.setFormatter(logging.Formatter(fmt))
        h.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(h_file)
    root.addHandler(h_out)

def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()

def check_env_file_perms():
    """Peringatkan bila .env terbaca user lain (kebersihan kredensial)."""
    p = ".env"
    if os.path.exists(p):
        mode = stat.S_IMODE(os.stat(p).st_mode)
        if mode & 0o077:
            logging.warning("KEAMANAN: %s permission %o — jalankan: chmod 600 .env", p, mode)

# ============================== 3. NOTIFIKASI ================================

class Telegram:
    def __init__(self, cfg: Config):
        # Fail-safe notifier (audit 29-Sep-2026): token invalid/rotated tidak boleh
        # membuat engine mengham­mer Telegram dengan panggilan gagal terus.
        self._disabled_reason: str | None = None
        tok = (cfg.tg_token or "").strip()
        fmt_ok = bool(tok) and ":" in tok and tok.split(":", 1)[0].isdigit()
        if cfg.tg_token and cfg.tg_chat and not fmt_ok:
            self.ok = False
            self._disabled_reason = "invalid_token_format"
        else:
            self.ok = bool(cfg.tg_token and cfg.tg_chat)
        self.url = f"https://api.telegram.org/bot{cfg.tg_token}/sendMessage" if self.ok else ""
        self.chat = cfg.tg_chat
    def health(self) -> dict:
        """Status kanal alert — dipakai monitoring (healthcheck) & test guard."""
        return {"ok": self.ok, "disabled_reason": self._disabled_reason}
    def send(self, text: str):
        logging.info("ALERT: %s", text)
        if not self.ok:
            return
        try:
            data = urllib.parse.urlencode({"chat_id": self.chat, "text": text[:3900]}).encode()
            req = urllib.request.Request(self.url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
        except urllib.error.HTTPError as e:
            # 401 = token dirotasi/dicabut → matikan kanal (fail-safe), jangan retry spam.
            if e.code in (401, 403):
                self.ok = False
                self._disabled_reason = "unauthorized_token_rotate_TELEGRAM_BOT_TOKEN"
            logging.warning("telegram gagal: %s", e)
        except Exception as e:  # alert gagal tidak boleh menjatuhkan engine
            logging.warning("telegram gagal: %s", e)

# ============================== 4. LEDGER (SQLite) ===========================

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, engine TEXT NOT NULL,
  bucket TEXT NOT NULL, pair TEXT NOT NULL, side TEXT NOT NULL,
  price TEXT NOT NULL, qty TEXT NOT NULL, notional TEXT NOT NULL,
  fee TEXT NOT NULL, maker INTEGER NOT NULL, rt_id TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS rts(
  rt_id TEXT PRIMARY KEY, ts_close TEXT, engine TEXT, pair TEXT,
  volume TEXT, net_pnl TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS weekly_points(
  week_sat TEXT PRIMARY KEY, points TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS e2_open_pos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair TEXT NOT NULL, side TEXT NOT NULL,
  qty TEXT NOT NULL, entry_px TEXT NOT NULL,
  opened_ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS e2_dir_signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair TEXT NOT NULL,
  side TEXT NOT NULL,
  grade TEXT NOT NULL,
  funding_rate TEXT,
  obi TEXT,
  entry_px TEXT NOT NULL,
  exit_px TEXT,
  qty TEXT NOT NULL,
  pnl TEXT,
  exit_reason TEXT,
  opened_ts TEXT NOT NULL,
  closed_ts TEXT);
"""

# Mode eksekusi proses ini — dicap ke setiap baris ledger (`rts.mode`/`fills.mode`).
# Default dry_run. main() hanya menaikkan ke "live" setelah 3 kunci live lolos.
MODE = "dry_run"


class Ledger:
    def __init__(self, path: str):
        self.con = sqlite3.connect(path, isolation_level=None)  # autocommit
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self._migrate_mode()

    def _migrate_mode(self):
        """Tambah kolom `mode` ke DB lama. Idempoten; tanpa backfill."""
        for tbl in ("rts", "fills"):
            cols = {r[1] for r in self.con.execute(f"PRAGMA table_info({tbl})")}
            if "mode" not in cols:
                self.con.execute(f"ALTER TABLE {tbl} ADD COLUMN mode TEXT")
    # ---- tulis ----
    def fill(self, engine, bucket, pair, side, price: Decimal, qty: Decimal,
             fee: Decimal, maker: bool, rt_id: str | None):
        self.con.execute(
            "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id,mode)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(UTC).isoformat(), engine, bucket, pair, side,
             str(price), str(qty), str(price * qty), str(fee), int(maker), rt_id, MODE))
    def rt_close(self, rt_id, engine, pair, volume: Decimal, net_pnl: Decimal,
                 ts: str | None = None):
        """Tutup round-trip — APPEND-ONLY. JANGAN pernah kembali ke INSERT OR REPLACE.

        ts = waktu KEJADIAN (default: sekarang). Insiden 28-Sep-2026: PK rt_id
        dipakai ulang antar sesi (penghitung `_rt` di-reset ke 0) sementara baris
        ditulis dengan INSERT OR REPLACE → 319 baris historis TERTIMPA dan metrik
        window membaca baris daur-ulang (weekly WR 29,23% = artefak).
        Bila ID bentrok, baris baru disimpan dengan sufiks unik → riwayat lama utuh.
        """
        t = ts or datetime.now(UTC).isoformat()
        try:
            self.con.execute(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl,mode)"
                " VALUES(?,?,?,?,?,?,?)",
                (rt_id, t, engine, pair, str(volume), str(net_pnl), MODE))
        except sqlite3.IntegrityError:
            alt = f"{rt_id}~{uuid.uuid4().hex[:8]}"
            self.con.execute(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl,mode)"
                " VALUES(?,?,?,?,?,?,?)",
                (alt, t, engine, pair, str(volume), str(net_pnl), MODE))
            print(f"[LEDGER] rt_id bentrok {rt_id} → disimpan {alt} "
                  f"(riwayat lama TIDAK ditimpa)", file=sys.stderr)
    _RT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-(\d+)$")
    def next_rt_seq(self, engine: str) -> int:
        """Nomor RT tertinggi yang SUDAH tercatat untuk engine ini (monotonik).

        Dipakai untuk meng-seed penghitung RT saat engine init. Sebelum perbaikan
        setiap sesi mulai dari 0 → ID E1-1.. dipakai ulang → baris historis
        tertimpa. Seed dari MAX(id) membuat ID tidak pernah dipakai ulang.
        """
        mx = 0
        for (rid,) in self.con.execute("SELECT rt_id FROM rts WHERE engine=?", (engine,)):
            m = self._RT_ID_RE.match(rid or "")
            if m:
                mx = max(mx, int(m.group(1)))
        return mx
    def set_state(self, k, v):  self.con.execute(
        "INSERT INTO state VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    def get_state_text(self, k, default="") -> str:
        """State sebagai string (untuk nilai non-numerik seperti equity_high_source)."""
        row = self.con.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return row[0] if row and row[0] is not None else default
    def set_state_text(self, k, v):
        self.con.execute(
            "INSERT INTO state VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    def get_state(self, k, default="0") -> Decimal:
        row = self.con.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return D(row[0]) if row else D(default)
    def record_points(self, week_sat: str, points: Decimal, note: str):
        self.con.execute("INSERT OR REPLACE INTO weekly_points VALUES(?,?,?)",
                         (week_sat, str(points), note))
    # ---- baca/agregasi ----
    def _sum(self, sql, args=()) -> Decimal:
        row = self.con.execute(sql, args).fetchone()
        return D(row[0]) if row and row[0] is not None else D(0)
    def fees_since(self, iso, engine=None) -> Decimal:
        if engine:
            return self._sum("SELECT SUM(CAST(fee AS REAL)) FROM fills WHERE ts>=? AND engine=?",
                             (iso, engine))
        return self._sum("SELECT SUM(CAST(fee AS REAL)) FROM fills WHERE ts>=?", (iso,))
    def volume_since(self, iso, bucket=None) -> Decimal:
        if bucket:
            return self._sum("SELECT SUM(CAST(notional AS REAL)) FROM fills WHERE ts>=? AND bucket=?",
                             (iso, bucket))
        return self._sum("SELECT SUM(CAST(notional AS REAL)) FROM fills WHERE ts>=?", (iso,))
    def e1_profit_since(self, iso) -> Decimal:
        return self._sum("SELECT SUM(CAST(net_pnl AS REAL)) FROM rts WHERE ts_close>=? AND engine='E1'",
                         (iso,))
    def total_profit_since(self, iso) -> Decimal:
        return self._sum("SELECT SUM(CAST(net_pnl AS REAL)) FROM rts WHERE ts_close>=?",
                         (iso,))
    def e1_recent_net_rate(self, n=200) -> Decimal | None:
        rows = self.con.execute(
            "SELECT net_pnl, volume FROM rts WHERE engine='E1' ORDER BY ts_close DESC LIMIT ?",
            (n,)).fetchall()
        if len(rows) < 30:
            return None
        pnl = sum(D(r[0]) for r in rows); vol = sum(D(r[1]) for r in rows)
        return (pnl / vol) if vol else None

    def e1_recent_net_rate_pair(self, pair: str, n: int = 100, min_n: int = 20,
                                since_iso: str | None = None):
        """B14/B17: net rate (pnl/volume) untuk PAIR tertentu atas n RT terakhir.
        Return (rate, jumlah) atau (None, jumlah) bila sampel < min_n.

        B17: since_iso memfilter HANYA RT JUJUR (post-B13). Gate keselamatan WAJIB
        pakai data jujur — RT phantom pra-B13 akan menipu gate mengira E1 profit."""
        if since_iso:
            rows = self.con.execute(
                "SELECT net_pnl, volume FROM rts WHERE engine='E1' AND pair=? "
                "AND ts_close >= ? ORDER BY ts_close DESC LIMIT ?",
                (pair, since_iso, n)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT net_pnl, volume FROM rts WHERE engine='E1' AND pair=? "
                "ORDER BY ts_close DESC LIMIT ?", (pair, n)).fetchall()
        if len(rows) < min_n:
            return None, len(rows)
        pnl = sum(D(r[0]) for r in rows); vol = sum(D(r[1]) for r in rows)
        return ((pnl / vol) if vol else None), len(rows)

    def e1_rts_since(self, since_iso: str, pair: str | None = None) -> list:
        """B19: daftar (net_pnl, volume) RT E1 sejak since_iso (utk eksperimen)."""
        if pair:
            rows = self.con.execute(
                "SELECT net_pnl, volume FROM rts WHERE engine='E1' AND pair=? "
                "AND ts_close >= ? ORDER BY ts_close", (pair, since_iso)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT net_pnl, volume FROM rts WHERE engine='E1' AND ts_close >= ? "
                "ORDER BY ts_close", (since_iso,)).fetchall()
        return [(D(str(r[0])), D(str(r[1]))) for r in rows]
    # ---- E2 crash-recovery: persistent open position state ----
    def e2_save_open(self, pair: str, side: str, qty: Decimal, entry_px: Decimal) -> int:
        """Record a confirmed E2 perps position. Returns rowid for later clear."""
        if qty <= 0 or entry_px <= 0:
            raise ValueError("E2 open-position record requires confirmed positive qty and entry_px")
        cur = self.con.execute(
            "INSERT INTO e2_open_pos(pair,side,qty,entry_px,opened_ts) VALUES(?,?,?,?,?)",
            (pair, side, str(qty), str(entry_px), datetime.now(UTC).isoformat()))
        return cur.lastrowid  # type: ignore[return-value]
    def e2_clear_open(self, rowid: int):
        """Remove E2 position record after successful close (crash recovery complete)."""
        self.con.execute("DELETE FROM e2_open_pos WHERE id=?", (rowid,))
    def e2_get_open_positions(self) -> list[dict]:
        """Return all recorded-but-unclosed E2 positions (for startup reconciliation)."""
        rows = self.con.execute(
            "SELECT id, pair, side, qty, entry_px, opened_ts FROM e2_open_pos"
        ).fetchall()
        return [{"id": r[0], "pair": r[1], "side": r[2],
                 "qty": D(r[3]), "entry_px": D(r[4]), "opened_ts": r[5]}
                for r in rows]
    def e2_clear_nonrecoverable_open_positions(self) -> int:
        """Delete legacy E2 rows that never represented a confirmed exchange position."""
        cur = self.con.execute(
            "DELETE FROM e2_open_pos WHERE CAST(qty AS REAL) <= 0 OR CAST(entry_px AS REAL) <= 0"
        )
        return int(cur.rowcount or 0)

    # ---- Phase 2: E2 Directional signal ledger ----
    def e2_dir_open(self, pair: str, side: str, grade: str,
                    funding_rate: Decimal, obi: "Decimal | None",
                    entry_px: Decimal, qty: Decimal) -> int:
        """Rekam sinyal direksional baru (posisi terbuka). Return row-id.
        S9 fix (06-Okt-2026): obi bisa None (tak tersedia dari adapter price-only)."""
        cur = self.con.execute(
            "INSERT INTO e2_dir_signals"
            "(pair,side,grade,funding_rate,obi,entry_px,qty,opened_ts)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (pair, side, grade, str(funding_rate), str(obi) if obi is not None else None,
             str(entry_px), str(qty), datetime.now(UTC).isoformat()))
        return cur.lastrowid  # type: ignore[return-value]

    def e2_dir_close(self, sig_id: int, exit_px: Decimal,
                     pnl: Decimal, exit_reason: str):
        """Tutup sinyal direksional (catat harga keluar, PnL, alasan)."""
        self.con.execute(
            "UPDATE e2_dir_signals SET exit_px=?,pnl=?,exit_reason=?,closed_ts=?"
            " WHERE id=?",
            (str(exit_px), str(pnl), exit_reason,
             datetime.now(UTC).isoformat(), sig_id))

    def e2_dir_open_signal(self, pair: str | None = None) -> dict | None:
        """Kembalikan sinyal direksional yang masih terbuka (belum closed_ts), atau None."""
        if pair:
            row = self.con.execute(
                "SELECT id,pair,side,grade,entry_px,qty,opened_ts"
                " FROM e2_dir_signals WHERE closed_ts IS NULL AND pair=?"
                " ORDER BY opened_ts DESC LIMIT 1", (pair,)).fetchone()
        else:
            row = self.con.execute(
                "SELECT id,pair,side,grade,entry_px,qty,opened_ts"
                " FROM e2_dir_signals WHERE closed_ts IS NULL"
                " ORDER BY opened_ts DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"id": row[0], "pair": row[1], "side": row[2], "grade": row[3],
                "entry_px": D(row[4]), "qty": D(row[5]), "opened_ts": row[6]}

    def e2_dir_open_signals(self) -> list[dict]:
        """B29: Kembalikan SEMUA sinyal direksional terbuka (untuk concurrent multi-signal).
        Diurutkan dari yang terlama agar posisi lama dikelola lebih dulu."""
        rows = self.con.execute(
            "SELECT id,pair,side,grade,entry_px,qty,opened_ts"
            " FROM e2_dir_signals WHERE closed_ts IS NULL"
            " ORDER BY opened_ts ASC").fetchall()
        return [{"id": r[0], "pair": r[1], "side": r[2], "grade": r[3],
                 "entry_px": D(r[4]), "qty": D(r[5]), "opened_ts": r[6]}
                for r in rows]

    def e2_dir_stats(self, pair: str | None = None, n: int = 1000) -> dict:
        """Statistik sinyal direksional: n, WR, E(R), total PnL.
        Hanya hitung sinyal yang sudah CLOSED (ada closed_ts & pnl)."""
        if pair:
            rows = self.con.execute(
                "SELECT pnl FROM e2_dir_signals WHERE pnl IS NOT NULL AND pair=?"
                " ORDER BY closed_ts DESC LIMIT ?", (pair, n)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT pnl FROM e2_dir_signals WHERE pnl IS NOT NULL"
                " ORDER BY closed_ts DESC LIMIT ?", (n,)).fetchall()
        if not rows:
            return {"n": 0, "n_win": 0, "win_rate": None,
                    "total_pnl": D(0), "mean_pnl": None}
        pnls = [D(str(r[0])) for r in rows]
        n_win = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        return {
            "n": len(pnls),
            "n_win": n_win,
            "win_rate": D(str(n_win)) / D(str(len(pnls))),
            "total_pnl": total,
            "mean_pnl": total / D(str(len(pnls))),
        }

    def e2_dir_budget_spent(self) -> Decimal:
        """Total kerugian kumulatif sinyal direksional (untuk cap budget)."""
        row = self.con.execute(
            "SELECT SUM(CAST(pnl AS REAL)) FROM e2_dir_signals"
            " WHERE pnl IS NOT NULL AND CAST(pnl AS REAL) < 0").fetchone()
        loss = D(str(row[0])) if row and row[0] is not None else D(0)
        return abs(loss)  # positif = total rugi

    # ── B33: Per-pair blacklist (pair dengan WR buruk di-cooldown sementara) ──

    def e2_dir_pair_blacklist(self, pair: str, cooldown_secs: float) -> None:
        """B33: Blacklist pair E2Dir selama cooldown_secs detik (simpan ke state)."""
        expiry = time.time() + cooldown_secs
        self.set_state(f"e2_dir_bl_{pair.replace('/', '_').replace('-', '_')}", str(expiry))

    def e2_dir_pair_is_blacklisted(self, pair: str) -> bool:
        """B33: True bila pair masih dalam masa cooldown blacklist."""
        key = f"e2_dir_bl_{pair.replace('/', '_').replace('-', '_')}"
        expiry = float(self.get_state(key))
        return expiry > time.time()

    def e2_dir_pair_wr(self, pair: str, last_n: int = 10) -> tuple[int, float | None]:
        """B33: Kembalikan (n_closed, win_rate) pair untuk last_n sinyal terakhir."""
        rows = self.con.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN CAST(pnl AS FLOAT) > 0 THEN 1 ELSE 0 END)
            FROM (
                SELECT pnl FROM e2_dir_signals
                WHERE pair = ? AND closed_ts IS NOT NULL
                ORDER BY id DESC LIMIT ?
            )
        """, (pair, last_n)).fetchone()
        if not rows or rows[0] == 0:
            return 0, None
        n, won = rows
        return n, (won / n) if n > 0 else 0.0

    # ── B34: Exit quality breakdown + binomial significance ──

    def e2_dir_exit_quality(self, pair: str | None = None) -> dict:
        """B34: Breakdown sinyal tertutup per exit_reason (tp/sl/timeout).

        Returns dict[reason → {n, won, wr, avg_pnl}].
        Dipakai untuk menghitung: apakah alpha datang dari TP hits (genuine
        directional move) atau hanya timeout-lucky (noise)?
        """
        where = "WHERE closed_ts IS NOT NULL"
        params: list = []
        if pair:
            where += " AND pair = ?"
            params.append(pair)
        rows = self.con.execute(f"""
            SELECT COALESCE(exit_reason,'unknown') AS reason,
                   COUNT(*) AS n,
                   SUM(CASE WHEN CAST(pnl AS FLOAT) > 0 THEN 1 ELSE 0 END) AS won,
                   AVG(CAST(pnl AS FLOAT)) AS avg_pnl
            FROM e2_dir_signals {where}
            GROUP BY reason ORDER BY n DESC
        """, params).fetchall()
        return {
            reason: {"n": n, "won": won,
                     "wr": (won / n) if n > 0 else None,
                     "avg_pnl": avg_pnl or 0.0}
            for reason, n, won, avg_pnl in rows
        }

    def e2_dir_binom_test(self, pair: str | None = None) -> dict:
        """B34: Binomial significance test untuk WR > 50% (one-tailed upper).

        Returns {n, won, wr, z, p_val, significant_p05, significant_p10}.
        Hipotesis nol: WR = 50% (tidak ada alpha). Tolak H0 bila p < 0.05.
        Butuh n ≥ 5 untuk pendekatan normal yang cukup akurat.
        """
        import math
        st = self.e2_dir_stats(pair)
        n = int(st["n"])
        if n < 5:
            return {"n": n, "won": 0, "wr": None, "z": None,
                    "p_val": None, "significant_p05": False, "significant_p10": False}
        won = int(n * float(st["win_rate"] or 0))
        wr = float(st["win_rate"] or 0)
        z = (wr - 0.5) / (0.5 / math.sqrt(n))
        # One-tailed p-value P(Z > z) = 0.5 × erfc(z / √2)
        p_val = 0.5 * math.erfc(z / math.sqrt(2)) if z > 0 else 1.0
        return {
            "n": n, "won": won, "wr": round(wr, 4), "z": round(z, 3),
            "p_val": round(p_val, 4),
            "significant_p05": p_val < 0.05,
            "significant_p10": p_val < 0.10,
        }

def week_start_iso(now=None) -> str:
    """Boundary snapshot SoDEX: Sabtu 00:00 UTC == Sabtu 07:00 WIB (WIB=UTC+7).
    Minggu poin = Sabtu→Sabtu. Selaras dengan snapshot sodex.com tiap Sabtu 07:00 WIB."""
    now = now or datetime.now(UTC)
    back = (now.weekday() - 5) % 7        # Sabtu=5
    sat = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
    return sat.isoformat()


def weekly_net_summary(led, now=None) -> dict:
    """Metrik MINGGUAN inti (sejak Sabtu 07:00 WIB): apakah profit E1 menutup
    biaya E2 sehingga net ≥ 0?

    Doktrin user: E1 = mesin profit (maksimalkan), E2 = mesin volume (cenderung
    rugi tipis). Target: net mingguan (E1 + E2) ≥ 0 — seimbang, cenderung tidak
    rugi, idealnya untung kecil. Dihitung pada horizon 7 hari sesuai snapshot
    sodex.com tiap Sabtu 07:00 WIB.

    Returns dict: week_start, e1_profit, e2_net, combined_net, vol_spot,
    vol_perps, vol_total, on_track (bool: combined_net ≥ 0), coverage_ratio
    (E1 profit / |E2 loss|, ∞ bila E2 ≥ 0).
    """
    wk = week_start_iso(now)
    e1 = led.e1_profit_since(wk)
    total = led.total_profit_since(wk)
    e2 = total - e1
    vol_spot = led.volume_since(wk, "S")
    vol_perps = led.volume_since(wk, "P")
    e2_loss = -e2 if e2 < 0 else Decimal(0)
    if e2_loss > 0:
        coverage = e1 / e2_loss   # >1 = E1 menutup penuh kerugian E2
    else:
        coverage = None           # E2 tidak rugi → tak perlu ditutup
    return {
        "week_start": wk,
        "e1_profit": e1,
        "e2_net": e2,
        "combined_net": total,
        "vol_spot": vol_spot,
        "vol_perps": vol_perps,
        "vol_total": vol_spot + vol_perps,
        "on_track": total >= 0,
        "coverage_ratio": coverage,
    }


# Map pair → coin balance (dipakai monitor & reconciler)
_MONITOR_COIN_MAP = {
    "PEPE/USDC": "vPEPE", "SHIB/USDC": "vSHIB",
    "SOL/USDC": "vSOL", "XLM/USDC": "vXLM",
}


def build_monitor_report(cfg: "Config", adapter, led, now=None) -> dict:
    """B16: Snapshot Monitoring & Evaluasi berbasis DATA RIIL SESUNGGUHNYA.

    Semua angka dari sumber riil — TIDAK ada estimasi/asumsi:
      • Sisa modal USD & aset trading → adapter.balance() (saldo riil exchange)
      • Ekuitas mark-to-market → saldo riil × harga mid riil (orderbook)
      • PnL/volume/rasio mingguan → ledger JUJUR (akunting balance-delta B13)
      • PnL mingguan SEBENARNYA (incl unrealized) → ekuitas_riil − ekuitas_awal_minggu

    Baseline ekuitas awal-minggu disimpan di state DB sekali per minggu (Sabtu
    07:00 WIB), sehingga MtM PnL mingguan akurat tanpa asumsi.

    Robust: kegagalan balance()/book() transien → field None + flag 'degraded',
    TIDAK crash (monitoring harus selalu jalan).
    """
    now = now or datetime.now(UTC)
    wk = week_start_iso(now)
    rep: dict = {"ts": now.isoformat(), "week_start": wk, "degraded": False}

    # ── 1. ASET TRADING & SISA MODAL USD (riil dari balance) ──
    usdc = None
    assets = []
    inv_usd_total = D(0)
    try:
        bal = adapter.balance()
        usdc = bal.get("vUSDC", D(0))
        for pair, coin in _MONITOR_COIN_MAP.items():
            qty = bal.get(coin, D(0))
            if qty <= 0:
                continue
            try:
                mid = adapter.book(pair).mid
            except Exception:
                mid = None
            usd = (qty * mid) if mid is not None else None
            if usd is not None:
                inv_usd_total += usd
            assets.append({
                "pair": pair, "coin": coin,
                "qty": float(qty),
                "mid": float(mid) if mid is not None else None,
                "usd": float(usd) if usd is not None else None,
            })
    except Exception as e:
        rep["degraded"] = True
        rep["degraded_reason"] = f"balance: {e}"

    real_equity = None
    if usdc is not None:
        real_equity = usdc + inv_usd_total
    rep["usdc_free"] = float(usdc) if usdc is not None else None
    rep["inventory_usd"] = float(inv_usd_total)
    rep["real_equity"] = float(real_equity) if real_equity is not None else None
    rep["assets"] = assets

    # ── 2. BASELINE EKUITAS AWAL-MINGGU (untuk MtM PnL akurat) ──
    mtm_pnl_week = None
    wk_start_eq = None
    if real_equity is not None:
        key = f"equity_wkstart_{wk}"
        stored = led.get_state(key)
        if not stored or float(stored) <= 0:
            led.set_state(key, real_equity)   # observasi pertama minggu ini = baseline
            wk_start_eq = real_equity
        else:
            wk_start_eq = D(str(stored))
        mtm_pnl_week = real_equity - wk_start_eq
    rep["equity_week_start"] = float(wk_start_eq) if wk_start_eq is not None else None
    rep["mtm_pnl_week"] = float(mtm_pnl_week) if mtm_pnl_week is not None else None

    # ── 3. PnL/VOLUME/RASIO MINGGUAN (ledger jujur) ──
    ws = weekly_net_summary(led, now)
    rep["e1_profit_week"] = float(ws["e1_profit"])
    rep["e2_net_week"] = float(ws["e2_net"])
    rep["realized_net_week"] = float(ws["combined_net"])
    rep["vol_spot_week"] = float(ws["vol_spot"])
    rep["vol_perps_week"] = float(ws["vol_perps"])
    rep["vol_total_week"] = float(ws["vol_total"])
    rep["on_track"] = bool(ws["on_track"])
    rep["coverage_ratio"] = (float(ws["coverage_ratio"])
                             if ws["coverage_ratio"] is not None else None)

    # ── 4. RASIO RIIL ──
    vol = ws["vol_total"]
    rep["net_rate_week"] = float(ws["combined_net"] / vol) if vol else None
    # win rate + jumlah RT minggu ini (per engine)
    rts = led.con.execute(
        "SELECT engine, net_pnl FROM rts WHERE ts_close >= ?", (wk,)).fetchall()
    n_rt = len(rts)
    wins = sum(1 for r in rts if float(r[1]) > 0)
    e1_n = sum(1 for r in rts if r[0] == "E1")
    e2_n = sum(1 for r in rts if r[0] == "E2")
    rep["rt_count_week"] = n_rt
    rep["rt_e1_week"] = e1_n
    rep["rt_e2_week"] = e2_n
    rep["win_rate_week"] = (wins / n_rt) if n_rt else None
    # efisiensi modal: PnL mingguan / ekuitas
    if real_equity and real_equity > 0:
        base = ws["combined_net"]
        rep["return_on_equity_week"] = float(base / real_equity)
    else:
        rep["return_on_equity_week"] = None

    # ── 5. KEJUJURAN KETAT: pisahkan data JUJUR (post-B13) dari TERCEMAR (phantom pra-B13) ──
    # Akunting jujur (balance-delta) baru aktif sejak B13. RT sebelum itu bisa
    # mengandung fill phantom (B9). Kita TIDAK menyembunyikan ini — laporkan apa adanya.
    b13_ts = led.get_state("b13_activated_ts")   # epoch (0 bila belum pernah)
    b13_iso = (datetime.fromtimestamp(float(b13_ts), UTC).isoformat()
               if b13_ts and float(b13_ts) > 0 else None)
    rep["b13_activated"] = b13_iso
    # batas data jujur dalam minggu ini = max(awal minggu, aktivasi B13)
    honest_since = wk
    week_contaminated = False
    if b13_iso and b13_iso > wk:
        honest_since = b13_iso
        week_contaminated = True   # sebagian minggu ini terjadi sebelum B13 → tercemar
    rep["honest_data_since"] = honest_since
    rep["week_has_contaminated_data"] = week_contaminated
    # statistik HANYA dari data jujur (post-B13)
    hrows = led.con.execute(
        "SELECT engine, net_pnl, volume FROM rts WHERE ts_close >= ?", (honest_since,)).fetchall()
    h_e1 = sum(D(str(r[1])) for r in hrows if r[0] == "E1")
    h_e2 = sum(D(str(r[1])) for r in hrows if r[0] == "E2")
    h_net = h_e1 + h_e2
    h_vol = sum(D(str(r[2])) for r in hrows)
    h_n = len(hrows)
    h_wins = sum(1 for r in hrows if float(r[1]) > 0)
    rep["honest_e1_profit"] = float(h_e1)
    rep["honest_e2_net"] = float(h_e2)
    rep["honest_net"] = float(h_net)
    rep["honest_vol"] = float(h_vol)
    rep["honest_rt_count"] = h_n
    rep["honest_net_rate"] = float(h_net / h_vol) if h_vol else None
    rep["honest_win_rate"] = (h_wins / h_n) if h_n else None
    rep["honest_on_track"] = bool(h_net >= 0)

    # ── 6. VERDICT EVALUASI (doktrin user: net mingguan ≥ 0) ──
    # Verdict UTAMA berbasis data JUJUR bila minggu tercemar; jika tidak, full-week.
    primary_on_track = rep["honest_on_track"] if week_contaminated else bool(ws["on_track"])
    rep["verdict"] = "SEIMBANG_ATAU_UNTUNG" if primary_on_track else "RUGI_E1_BELUM_TUTUP_E2"
    rep["verdict_basis"] = "honest_post_b13" if week_contaminated else "full_week"

    # ── 7. PHASE 2: E2Dir (B21/B26/B29) ──
    # Sertakan stats Phase 2 bila aktif — transparansi penuh.
    # B26: Tampilkan in-flight capital (posisi terbuka belum closed) terpisah
    # dari "budget terpakai" (hanya dari kerugian terealisasi).
    # B29: Dukung sinyal serentak — hitung inflight dari SEMUA posisi terbuka.
    e2_dir_st = led.e2_dir_stats(cfg.e2_dir_pair)
    e2_dir_spent = led.e2_dir_budget_spent()
    # B29: Ambil SEMUA posisi terbuka (bukan hanya satu)
    e2_dir_opens = led.e2_dir_open_signals()
    e2_dir_open = e2_dir_opens[0] if e2_dir_opens else None   # backward-compat (pair/side)
    e2_dir_inflight = sum(
        float(D(str(p["entry_px"])) * D(str(p["qty"]))) for p in e2_dir_opens)
    rep["e2_dir_enabled"] = cfg.e2_dir_enabled
    rep["e2_dir_pair"] = cfg.e2_dir_pair
    rep["e2_dir_n"] = e2_dir_st["n"]
    rep["e2_dir_win_rate"] = float(e2_dir_st["win_rate"]) if e2_dir_st["win_rate"] is not None else None
    rep["e2_dir_total_pnl"] = float(e2_dir_st["total_pnl"]) if e2_dir_st["total_pnl"] is not None else 0.0
    rep["e2_dir_budget_spent"] = float(e2_dir_spent)
    rep["e2_dir_budget_remaining"] = float(cfg.e2_dir_budget - e2_dir_spent)
    rep["e2_dir_inflight_usd"] = e2_dir_inflight  # B26: modal terkunci di posisi aktif
    rep["e2_dir_open_pair"] = e2_dir_open["pair"] if e2_dir_open else None
    rep["e2_dir_open_side"] = e2_dir_open["side"] if e2_dir_open else None
    rep["e2_dir_concurrent"] = len(e2_dir_opens)  # B29: jumlah posisi serentak
    # Gate status: fail-open bila n<min_n; HALT bila WR<40% & n≥min_n
    if e2_dir_st["n"] < cfg.e2_dir_min_n:
        rep["e2_dir_gate"] = "fail_open"
    elif e2_dir_st["win_rate"] is not None and e2_dir_st["win_rate"] < D("0.40"):
        rep["e2_dir_gate"] = "halt_low_wr"
    else:
        rep["e2_dir_gate"] = "ok"

    # ── 8. B28: Status B14 Gate (deteksi death spiral) ──
    # Bila B14 sudah pause lama → E1 tidak bisa self-recover (no new RTs = frozen rate).
    # Operator perlu tahu berapa jam gate sudah lock.
    b14_pause_ts = led.get_state("b14_pause_since_ts")
    if float(b14_pause_ts) > 0:
        locked_secs = time.time() - float(b14_pause_ts)
        rep["b14_status"] = "PAUSED"
        rep["b14_locked_hours"] = round(locked_secs / 3600, 2)
        rep["b14_pause_since"] = datetime.fromtimestamp(
            float(b14_pause_ts), UTC).isoformat()
    else:
        rep["b14_status"] = "ACTIVE"
        rep["b14_locked_hours"] = 0.0
        rep["b14_pause_since"] = None

    # ── 9. B30: Trial period status ──
    trial_until = float(led.get_state("b14_trial_until_ts"))
    if trial_until > time.time():
        rep["b30_trial_active"] = True
        rep["b30_trial_remaining_h"] = round((trial_until - time.time()) / 3600, 2)
        rep["b30_trial_until"] = datetime.fromtimestamp(trial_until, UTC).isoformat()
    else:
        rep["b30_trial_active"] = False
        rep["b30_trial_remaining_h"] = 0.0
        rep["b30_trial_until"] = None

    # ── 10. B31: Inventory risk alert ──
    # Bila E1 paused > 2 jam DAN masih ada inventory coin > $0.50 → dead capital alert
    b14_locked_h = rep.get("b14_locked_hours", 0.0)
    inv_usd = rep.get("inventory_usd", 0.0)
    assets = rep.get("assets", [])
    rep["b31_inventory_risk"] = (
        b14_locked_h > 2.0 and inv_usd > 0.50 and rep.get("b14_status") == "PAUSED"
    )
    if rep["b31_inventory_risk"]:
        # Identifikasi pair mana yang stuck
        stuck = [f"{a['pair']}=${a['usd']:.2f}" for a in assets if a.get("usd", 0) > 0.50]
        rep["b31_stuck_pairs"] = stuck
        rep["b31_stuck_usd"] = inv_usd
    else:
        rep["b31_stuck_pairs"] = []
        rep["b31_stuck_usd"] = 0.0

    # ── 11. B32: Per-pair E2Dir stats (diagnosa kualitas pair) ──
    # Untuk setiap pair yang pernah trading E2Dir, hitung: n, won, WR, total_pnl.
    # Ini memungkinkan operator melihat pair mana yang profit vs rugi.
    try:
        pair_rows = led.con.execute("""
            SELECT pair,
                   COUNT(*) AS n,
                   SUM(CASE WHEN CAST(pnl AS FLOAT) > 0 THEN 1 ELSE 0 END) AS won,
                   SUM(CAST(pnl AS FLOAT)) AS total_pnl,
                   AVG(ABS(CAST(funding_rate AS FLOAT))) AS avg_abs_fr
            FROM e2_dir_signals
            WHERE closed_ts IS NOT NULL
            GROUP BY pair
            ORDER BY n DESC
        """).fetchall()
        per_pair = []
        for row in pair_rows:
            pair_name, n_p, won_p, pnl_p, avg_fr = row
            wr_p = (won_p / n_p) if n_p > 0 else None
            per_pair.append({
                "pair": pair_name,
                "n": n_p,
                "won": won_p,
                "wr": round(float(wr_p), 4) if wr_p is not None else None,
                "pnl": round(float(pnl_p or 0), 4),
                "avg_abs_fr": round(float(avg_fr or 0), 6),
            })
        rep["e2_dir_per_pair"] = per_pair
    except Exception:
        rep["e2_dir_per_pair"] = []

    # ── 12. B34: Exit quality breakdown + binomial significance test ──
    try:
        eq = led.e2_dir_exit_quality()
        rep["e2_dir_exit_quality"] = {
            reason: {"n": d["n"], "won": d["won"],
                     "wr": round(float(d["wr"] or 0), 4),
                     "avg_pnl": round(float(d["avg_pnl"] or 0), 6)}
            for reason, d in eq.items()
        }
        bt = led.e2_dir_binom_test()
        rep["e2_dir_binom_z"]   = bt["z"]
        rep["e2_dir_binom_p"]   = bt["p_val"]
        rep["e2_dir_sig_p05"]   = bt["significant_p05"]   # p<0.05 → signifikan
        rep["e2_dir_go_live_ok"] = (
            bt["significant_p05"]
            and bt["n"] >= cfg.e2_dir_min_n
            and float(e2_dir_st.get("win_rate") or 0) >= 0.50
        )
    except Exception:
        rep["e2_dir_exit_quality"] = {}
        rep["e2_dir_binom_z"] = None
        rep["e2_dir_binom_p"] = None
        rep["e2_dir_sig_p05"] = False
        rep["e2_dir_go_live_ok"] = False

    return rep


def analyze_spread_samples(samples: list, fee_round_trip_bps: float) -> dict:
    """B18: Analisis distribusi spread (riset edge E1, ilmiah & nol-risiko).

    Hipotesis: maker pasif rugi karena quote saat spread terlalu tipis menutup
    fee + adverse selection. Pertanyaan: seberapa sering spread cukup lebar?

    Args:
        samples: list dict berisi 'spread_bps' (per pair).
        fee_round_trip_bps: fee maker bolak-balik dalam bps (2×maker_fee×1e4).

    Returns dict per-pair: n, min/median/p75/p90/max spread_bps, dan
    fraksi waktu spread ≥ ambang {fee×2, fee×4, 30, 40, 50 bps}.
    Breakeven KASAR butuh spread > ~2×fee + 2×adverse; tanpa nilai adverse,
    laporkan distribusi mentah agar keputusan berbasis bukti, bukan tebakan.
    """
    by_pair: dict = {}
    for s in samples:
        p = s.get("pair", "?")
        by_pair.setdefault(p, []).append(float(s.get("spread_bps", 0)))

    def _pct(sorted_xs, q):
        if not sorted_xs:
            return None
        idx = min(len(sorted_xs) - 1, int(q * len(sorted_xs)))
        return sorted_xs[idx]

    out: dict = {"fee_round_trip_bps": fee_round_trip_bps, "pairs": {}}
    thresholds = {
        "ge_2x_fee": fee_round_trip_bps * 2,
        "ge_4x_fee": fee_round_trip_bps * 4,
        "ge_30bps": 30.0,
        "ge_40bps": 40.0,
        "ge_50bps": 50.0,
    }
    for pair, xs in by_pair.items():
        if not xs:
            continue
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        frac = {k: round(sum(1 for x in xs if x >= thr) / n, 4)
                for k, thr in thresholds.items()}
        out["pairs"][pair] = {
            "n": n,
            "min_bps": round(xs_sorted[0], 2),
            "median_bps": round(_pct(xs_sorted, 0.50), 2),
            "p75_bps": round(_pct(xs_sorted, 0.75), 2),
            "p90_bps": round(_pct(xs_sorted, 0.90), 2),
            "max_bps": round(xs_sorted[-1], 2),
            "frac_ge": frac,
        }
    return out


def experiment_verdict(rt_pnls: list, vols: list, target_n: int,
                       budget_usd: float, min_n: int = 30) -> dict:
    """B19: Decision rule PRE-REGISTERED untuk eksperimen edge E1 (spread lebar).

    Hipotesis H1: maker profit (net rate > 0) bila quote HANYA saat spread lebar.
    Null H0: net rate tetap ≤ 0 (adverse selection ≥ cushion spread).

    Statistik: mean PnL/RT ± 95% CI (mean ± 1,96·SE). Keputusan:
      • CI bawah > 0  → H1_SUPPORTED (profit signifikan) → set min_spread, lanjut Fase 2
      • CI atas  < 0  → H1_FALSIFIED (rugi signifikan walau spread lebar) → pivot
      • lainnya       → INCONCLUSIVE (perlu data / budget lebih)
      • n < min_n     → INSUFFICIENT_N

    Status berjalan: HALTED_BUDGET (rugi ≥ budget), COMPLETE (n≥target), RUNNING.
    """
    import statistics
    n = len(rt_pnls)
    pnl_sum = sum(rt_pnls)
    vol_sum = sum(vols)
    net_rate = (pnl_sum / vol_sum) if vol_sum else None
    mean_pnl = (pnl_sum / n) if n else None
    if n > 1:
        sd = statistics.stdev([float(x) for x in rt_pnls])
        se = sd / (n ** 0.5)
        ci_low = mean_pnl - 1.96 * se
        ci_high = mean_pnl + 1.96 * se
    else:
        sd = se = ci_low = ci_high = None
    budget_spent = float(-pnl_sum) if pnl_sum < 0 else 0.0

    # status berjalan
    if budget_spent >= budget_usd:
        status = "HALTED_BUDGET"
    elif n >= target_n:
        status = "COMPLETE"
    else:
        status = "RUNNING"

    # verdict ilmiah (hanya final bila tidak RUNNING, atau sudah cukup sampel)
    if n < min_n:
        verdict = "INSUFFICIENT_N"
    elif ci_low is not None and ci_low > 0:
        verdict = "H1_SUPPORTED"
    elif ci_high is not None and ci_high < 0:
        verdict = "H1_FALSIFIED"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "n": n, "pnl_sum": float(pnl_sum), "vol_sum": float(vol_sum),
        "net_rate": float(net_rate) if net_rate is not None else None,
        "mean_pnl": float(mean_pnl) if mean_pnl is not None else None,
        "ci_low": ci_low, "ci_high": ci_high,
        "budget_spent": budget_spent, "budget_usd": budget_usd,
        "budget_remaining": max(0.0, budget_usd - budget_spent),
        "target_n": target_n, "status": status, "verdict": verdict,
    }


def persist_monitor_snapshot(cfg: "Config", report: dict):
    """Tulis snapshot ke time-series JSONL (audit/tren) + file 'latest' atomik."""
    try:
        os.makedirs(os.path.dirname(cfg.monitor_path) or ".", exist_ok=True)
        with open(cfg.monitor_path, "a") as f:
            f.write(json.dumps(report) + "\n")
        # 'latest' atomik (tmp + rename)
        tmp = cfg.monitor_latest + ".tmp"
        with open(tmp, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, cfg.monitor_latest)
    except Exception as e:
        logging.warning("persist_monitor_snapshot gagal: %s", e)

# =========================== 5. ADAPTER PERTUKARAN ===========================

@dataclass
class Book:
    bid: Decimal; ask: Decimal
    @property
    def mid(self): return (self.bid + self.ask) / 2
    @property
    def spread(self): return (self.ask - self.bid) / self.mid

@dataclass
class Order:
    oid: str; pair: str; side: str; price: Decimal; qty: Decimal
    filled: Decimal = D(0); ts: float = field(default_factory=time.time)
    cl_ord_id: str = ""   # client order ID wajib API SoDEX (added Jun 2026)

class ExchangeAdapter(ABC):
    """Kontrak minimal. SEMUA strategi hanya bicara lewat interface ini."""
    @abstractmethod
    def list_pairs(self) -> list[str]: ...
    @abstractmethod
    def book(self, pair: str) -> Book: ...
    @abstractmethod
    def place_post_only(self, pair: str, side: str, price: Decimal, qty: Decimal) -> Order: ...
    @abstractmethod
    def cancel(self, order: Order) -> None: ...
    @abstractmethod
    def poll_fill(self, order: Order) -> Decimal:
        """Kembalikan TAMBAHAN qty yang terisi sejak poll terakhir (0 jika belum)."""
    @abstractmethod
    def funding_rate(self, pair: str) -> Decimal: ...
    def cancel_all_spot_orders(self) -> int:
        """Batalkan semua order spot terbuka. Implementasi opsional (default no-op)."""
        return 0
    def account_equity(self) -> "Decimal | None":
        """Ekuitas akun riil (G4 guard). Default None = adapter tak mendukung
        (paper/dry-run); SodexLiveAdapter override dengan MtM riil."""
        return None

class PaperAdapter(ExchangeAdapter):
    """Simulator konservatif untuk dry-run/selftest. Random-walk + fill probabilistik
    dengan adverse selection ringan (fill lebih mungkin saat harga bergerak melawan)."""
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.px = {cfg.spot_pair: D("0.00000278"),     # PEPE
                   cfg.churn_perp: D("68000")}           # BTC
        self.spr = {cfg.spot_pair: D("0.0035"),          # PEPE ~0.35%
                    cfg.churn_perp: D("0.00008")}         # BTC ~0.008%
        # Fase 1: tambah pair kedua jika dikonfigurasi
        if cfg.spot_pair_2:
            self.px[cfg.spot_pair_2] = D("0.00000482")   # SHIB
            self.spr[cfg.spot_pair_2] = D("0.0020")       # SHIB ~0.20%
        self._n = 0
    def list_pairs(self): return list(self.px)
    def _step(self, pair):
        drift = D(RNG.uniform(-0.0006, 0.0006))
        self.px[pair] *= (1 + drift)
    def book(self, pair):
        self._step(pair)
        m, s = self.px[pair], self.spr[pair]
        return Book(bid=m * (1 - s / 2), ask=m * (1 + s / 2))
    def place_post_only(self, pair, side, price, qty):
        self._n += 1
        return Order(oid=f"P{self._n}", pair=pair, side=side, price=price, qty=qty)
    def place_market_ioc(self, pair, side, qty, ref_px, reduce_only=False):
        self._n += 1
        return Order(oid=f"M{self._n}", pair=pair, side=side, price=ref_px, qty=qty, filled=qty)
    def place_limit_ioc_perp(self, perp, side, qty, price):
        self._n += 1
        return Order(oid=f"L{self._n}", pair=perp, side=side, price=price, qty=qty, filled=qty)
    def cancel(self, order): pass
    def _sodex_list(self, args, timeout=30):
        return []  # paper: tidak ada exchange state, kembalikan list kosong
    def poll_fill(self, order):
        if order.filled >= order.qty:
            return D(0)
        # peluang fill per poll ~35%; sesekali partial (realistis utk maker tipis)
        if RNG.random() < 0.35:
            frac = D(1) if RNG.random() < 0.7 else D(str(RNG.uniform(0.3, 0.9)))
            inc = min(order.qty - order.filled, order.qty * frac)
            order.filled += inc
            return inc
        return D(0)
    def funding_rate(self, pair): return D(str(RNG.uniform(-0.0001, 0.0003)))

class SodexLiveAdapter(ExchangeAdapter):
    """
    ★ PRODUCTION ADAPTER — terhubung ke bin/sodex CLI (teruji 15 RT live).
    
    Semua method menggunakan syntax CLI yang SUDAH DIVERIFIKASI bekerja
    (Jun 6-11, 2026). GTX (post-only) tidak didukung SoDEX spot —
    fallback ke GTC dengan harga di dalam spread.
    """
    _SIDES = {"buy", "sell"}
    
    # Mapping: pair name → symbol-id (dari SoDEX CLI v2 — Jun 2026 upgrade)
    _SYMBOL_MAP = {
        "PEPE/USDC": 5,
        "SHIB/USDC": 15,      # WAS: 22 — FIXED post-upgrade
        "SOL/USDC": 7,         # Jun 16: 3rd pair, high notional
        "XLM/USDC": 22,        # Jun 16: 4th pair, wide spread 0.137%
        "DOGE/USDC": 8,        # available
        "ADA/USDC": 11,        # available
        "USDT/USDC": 27,       # E1-XR batch-1 (28-Sep): spread 40bps, vol $2,9K/hari
        "AVAX/USDC": 19,       # E1-XR batch-1: 9,2bps di atas floor fee 7bps
        "TSLA/USDC": 28,       # E1-XR batch-2: 7,0bps
        "BOXX/USDC": 36,       # E1-XR batch-2: 50,7bps, likuid $1,2K/hari
        "QQQ/USDC": 41,        # E1-XR batch-3: 60bps, likuid THIN ($150/hari)
        "SCHD/USDC": 37,       # E1-XR batch-3: 54bps, likuid THIN ($96/hari)
        "BTC-USD": 1,
        "ETH-USD": 2,
        "SOL-USD": 6,
        "HYPE-USD": 12,       # Jun 16: E2 — 0.004% spread (not profitable for pure MM)
        "ENA-USD": 25,       # Jun 17: 0.113% spread, $14K depth — PROFITABLE ✅
        "XPL-USD": 21,       # Jun 17: 0.107% spread, $22K depth — PROFITABLE ✅
        "TON-USD": 79,       # Jun 17: 0.213% spread, 395 qty — PROFITABLE ✅
        "SPCX-USD": 81,
    }
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # Use project's bin/sodex with .env credentials
        self._sodex_bin = cfg.sodex_cli or str(
            Path(__file__).resolve().parent.parent / "bin" / "sodex")
        if not os.path.exists(self._sodex_bin):
            raise SystemExit(f"SODEX CLI tidak ditemukan: {self._sodex_bin}")
        
        # Load credentials from .env
        self._env = os.environ.copy()
        # NOTE: SODEX_API_KEY intentionally excluded — blocks perps orders!
        for key in ["SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS"]:
            if key not in self._env:
                try:
                    r = subprocess.run(
                        f"grep {key} .env | cut -d= -f2",
                        shell=True, capture_output=True, text=True, timeout=5,
                        cwd=str(Path(__file__).resolve().parent.parent))
                    if r.stdout.strip():
                        self._env[key] = r.stdout.strip()
                except Exception:
                    pass
        if "SODEX_PRIVATE_KEY" not in self._env:
            raise SystemExit("SODEX_PRIVATE_KEY tidak ditemukan di environment/.env")
    
    def _sym_id(self, pair: str) -> int | None:
        """Convert pair name to SoDEX symbol-id. Returns None if unknown."""
        return self._SYMBOL_MAP.get(pair)
    
    def _sodex_list(self, args: list[str], timeout: int = 30) -> list[dict]:
        """Seperti _sodex tapi return FULL list (untuk orders list, dll.).
        _sodex() meng-collapse list ke data[0] — method ini tidak.
        OS-level timeout wrapper for reliable killing."""
        cmd = ["timeout", str(timeout - 2), self._sodex_bin] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, env=self._env)
            if r.returncode == 124:  # timeout killed
                logging.warning("sodex_list OS timeout: %s", " ".join(args))
                return []
            if r.returncode != 0:
                logging.warning("sodex_list error: %s", r.stderr.strip()[:200])
                return []
            out = r.stdout.strip()
            if not out:
                return []
            data = json.loads(out)
            if isinstance(data, list):
                return data
            return [data] if data else []
        except subprocess.TimeoutExpired:
            logging.warning("sodex_list timeout: %s", " ".join(args))
            return []
        except json.JSONDecodeError:
            logging.warning("sodex_list bad JSON: %s", out[:100] if 'out' in locals() else "")
            return []
        except Exception as e:
            logging.warning("sodex_list exception: %s", e)
            return []

    def _sodex(self, args: list[str], timeout: int = 30, retries: int = 2) -> dict:
        """Panggil bin/sodex dengan env kredensial. Return parsed JSON.
        Retry on transient network errors (DNS, connection).
        OS-level timeout wrapper: kills hung subprocess reliably."""
        # Use OS timeout command for reliable process killing
        cmd = ["timeout", str(timeout - 2), self._sodex_bin] + args
        last_err = ""
        for attempt in range(retries + 1):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, env=self._env)
                if r.returncode == 124:  # timeout command exit code
                    logging.warning("sodex timeout (OS): %s", " ".join(args))
                    return {}
                if r.returncode != 0:
                    err = r.stderr.strip()[:200]
                    if any(kw in err.lower() for kw in ('dns', 'lookup', 'timeout', 'connection refused', 'eof')):
                        last_err = err
                        if attempt < retries:
                            time.sleep(1.5 * (attempt + 1))
                            continue
                    logging.warning("sodex error: %s", err)
                    return {}
                out = r.stdout.strip()
                if not out:
                    return {}
                data = json.loads(out)
                if isinstance(data, list):
                    return data[0] if data else {}
                return data
            except subprocess.TimeoutExpired:
                last_err = "timeout"
                if attempt < retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                logging.warning("sodex timeout (retries exhausted): %s", " ".join(args))
                return {}
            except json.JSONDecodeError:
                logging.warning("sodex bad JSON: %s", out[:100] if 'out' in locals() else "")
                return {}
            except Exception as e:
                last_err = str(e)[:100]
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                logging.warning("sodex exception: %s", e)
                return {}
        logging.warning("sodex all retries failed: %s", last_err)
        return {}
    
    # ── ExchangeAdapter implementation ──
    
    def list_pairs(self) -> list[str]:
        """Return known working pairs (hardcoded — CLI tidak punya 'pairs' command).
        HANYA pairs dengan symbol-id terverifikasi yang direturn."""
        return [k for k, v in self._SYMBOL_MAP.items() if v is not None]
    
    def balance(self) -> dict[str, Decimal]:
        """Query exchange spot balance. Returns {coin: total}."""
        rows = self._sodex_list(["balance", "spot", "--format", "json"], timeout=15)
        if not rows:
            return {}
        return {b.get("coin", ""): D(str(b.get("total", 0))) for b in rows if b.get("coin")}

    # ── G4 FIX (audit 2026-09-27): ekuitas AKUN RIIL — satu sumber kebenaran ──
    # Root cause crash-loop 48× restart WIB 21:00-22:44: equity_estimate() lama
    # = capital($30)+ledger(+36,1)=$66,15 SEMENTARA ekuitas riil $61,63. Ratchet
    # equity_high mengunci angka ledger → drawdown SEMU 6,8% ≥ 6% → HARD STOP →
    # watchdog restart → berulang. Ledger overstatement $4,5 tidak terdeteksi.
    # Sekarang: guard WAJIB pakai angka akun riil (spot MtM + perps av); ledger
    # TIDAK PERNAH dicampurkan lagi — saat live dan akun gagal dibaca → None
    # (skip check), bukan fallback ke angka yang tidak sebanding.
    _STABLE_COINS = {"vUSDC", "USDC"}

    def _api_get(self, path: str, timeout: int = 15):
        base = self._env.get("SODEX_PERPS_URL",
                             "https://mainnet-gw.sodex.dev/api/v1/perps")
        base = base[: base.find("/api/v1") + 7] if "/api/v1" in base else base
        req = urllib.request.Request(base + path,
                                     headers={"User-Agent": "anantara-twin/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def account_equity(self) -> Decimal | None:
        """Ekuitas RIIL = USDC spot + inventori spot MtM (mid ticker) + av perps.
        Fail-closed: exception → None (guard skip, TIDAK pakai ledger campur)."""
        try:
            addr = (self._env.get("SODEX_ADDRESS") or "").lower()
            if not addr:
                return None
            bal_rows = (self._api_get(f"/spot/accounts/{addr}/balances")
                        .get("data", {}) or {}).get("balances", [])
            td = self._api_get("/spot/markets/tickers").get("data", [])
            # API SoDEX: `data` bisa dict{tickers:[...]} ATAU list langsung
            # (terverifikasi live 27-Sep — bug fix parsing list -> guard buta).
            tickers = td.get("tickers", []) if isinstance(td, dict) else td
            mid_map: dict[str, Decimal] = {}
            for t in tickers:
                try:
                    mid_map[str(t.get("symbol", ""))] = (D(str(t.get("bidPx", 0))) + D(str(t.get("askPx", 0)))) / 2
                except Exception:
                    continue
            total = D(0)
            for b in bal_rows:
                coin = str(b.get("coin", ""))
                qty = D(str(b.get("total", 0) or 0))
                if qty <= 0:
                    continue
                if coin in self._STABLE_COINS:
                    total += qty
                    continue
                mid = mid_map.get(f"v{coin.removeprefix('v')}_vUSDC") or mid_map.get(f"{coin}_vUSDC")
                if mid is not None:
                    total += qty * mid
                # coin tanpa ticker (dust exotic) → terlewat; nilainya <$0,01,
                # konservatif untuk drawdown guard.
            try:
                st = self._api_get(f"/perps/accounts/{addr}/state").get("data", {}) or {}
                av = st.get("av")
                if av is not None:
                    total += D(str(av))
            except Exception:
                pass
            return total
        except Exception as e:
            logging.debug("account_equity gagal: %s", e)
            return None

    def book(self, pair: str) -> Book:
        """Get orderbook via bin/sodex orderbook spot/perps <PAIR> --depth 1 --format json."""
        # PERPS pairs: "BTC-USD", "PEPE-USD"
        if "-USD" in pair.upper():
            j = self._sodex(["orderbook", "perps", pair, "--depth", "1", "--format", "json"])
        else:
            j = self._sodex(["orderbook", "spot", pair, "--depth", "1", "--format", "json"])
        
        if not j or "bids" not in j or not j["bids"] or not j["asks"]:
            raise RuntimeError(f"Orderbook gagal untuk {pair}: {j}")
        return Book(
            bid=D(str(j["bids"][0]["price"])),
            ask=D(str(j["asks"][0]["price"]))
        )
    
    def place_post_only(self, pair: str, side: str, price: Decimal, qty: Decimal) -> Order:
        """
        Place limit order. GTX (post-only) TIDAK DIDUKUNG SoDEX —
        gunakan GTC dengan harga agresif di dalam spread sebagai gantinya.
        """
        if side not in self._SIDES:
            raise ValueError(f"side invalid: {side}")
        
        # Determine market type
        is_perp = "-USD" in pair.upper()
        market = "perps" if is_perp else "spot"
        sym = pair

        # S12 fix (audit 06-Okt-2026): fungsi ini NAMANYA post-only tapi kirim
        # GTC verbatim dari harga yg caller hitung -- TANPA klem di sini. Kalau
        # caller salah hitung / book sudah bergerak sebelum order terkirim,
        # order bisa SILANG spread jadi TAKER (fee 0,040% vs maker 0,012%,
        # 3,3x lebih mahal) tanpa peringatan apa pun. Defense-in-depth: klem
        # ulang di titik PALING AKHIR sebelum dikirim ke exchange.
        try:
            bk = self.book(pair)
            if side == "buy" and price >= bk.ask:
                safe_px = bk.ask * (D("1") - D("0.0001"))  # 1bp di bawah ask
                logging.warning(
                    "place_post_only: price %.8f >= ask %.8f (%s %s) -- "
                    "diklem ke %.8f utk cegah taker-cross (S12 fix)",
                    float(price), float(bk.ask), side, pair, float(safe_px))
                price = safe_px
            elif side == "sell" and price <= bk.bid:
                safe_px = bk.bid * (D("1") + D("0.0001"))  # 1bp di atas bid
                logging.warning(
                    "place_post_only: price %.8f <= bid %.8f (%s %s) -- "
                    "diklem ke %.8f utk cegah taker-cross (S12 fix)",
                    float(price), float(bk.bid), side, pair, float(safe_px))
                price = safe_px
        except Exception as e:
            logging.warning("place_post_only: gagal verifikasi klem anti-cross (%s) -- lanjut tanpa klem", e)
        
        # Tick-size-aware price & quantity formatting
        # ponytail: perps qty precision based on price magnitude
        if price < D("0.0001"):
            px_str = f"{float(price):.8f}"   # PEPE, SHIB — micro-price
            qty_str = str(math.ceil(float(qty)))   # ceil: jaga notional ≥ min (bug 28-Sep: int() trunc ke bawah → $4.99<$5 reject di sub-$1)
        elif price < D("1"):
            px_str = f"{float(price):.4f}"   # XLM, DOGE — sub-dollar
            qty_str = str(math.ceil(float(qty)))
        elif is_perp:
            # Perps qty: needs enough decimals for high-price pairs (BTC $63K, ETH $1.7K)
            if price < D("10"):
                px_str = f"{float(price):.3f}"
                qty_str = f"{float(qty):.4f}"   # SOL, HYPE — ~$1-10, qty 0.1-10
            elif price < D("1000"):
                px_str = f"{float(price):.2f}"
                qty_str = f"{float(qty):.4f}"   # mid-price perps
            elif price < D("10000"):
                px_str = f"{float(price):.2f}"
                qty_str = f"{float(qty):.5f}"   # ETH ~$1700, qty ~0.08
            else:
                px_str = f"{float(price):.2f}"
                qty_str = f"{float(qty):.6f}"   # BTC ~$63700, qty ~0.0027
        else:
            px_str = f"{float(price):.2f}"   # SOL, HYPE — dollar-price
            qty_str = f"{float(qty):.3f}"   # spot SOL
        
        j = self._sodex([
            "orders", "place", market,
            "--symbol", sym,
            "--side", side,
            "--price", px_str,
            "--qty", qty_str,
            "--type", "limit",
            "--tif", "gtc",       # GTX tidak didukung — gunakan GTC
            "--format", "json"
        ], timeout=30)

        # Ekstraksi oid ROBUST: coba beberapa nama field + nested (data/order).
        # Respons place mungkin beda dari respons list. Mencegah false-"gagal"
        # bila CLI memakai orderId/id/order_id atau membungkus dalam data/order.
        def _extract_oid(resp) -> str:
            if not isinstance(resp, dict):
                return ""
            for k in ("orderID", "orderId", "order_id", "id"):
                v = resp.get(k)
                if v not in (None, 0, "0", ""):
                    return str(v)
            for nest in ("data", "order", "result"):
                inner = resp.get(nest)
                if isinstance(inner, dict):
                    got = _extract_oid(inner)
                    if got:
                        return got
            return ""

        oid = _extract_oid(j)
        cl_id = j.get("clOrdID", f"sodex-twin-{int(time.time())}") if isinstance(j, dict) else ""

        # oid kosong: order TIDAK terpasang. Dump respons MENTAH (truncated) agar
        # akar penyebab terlihat di log — respons order tidak memuat secret.
        if not oid:
            err = ""
            if isinstance(j, dict):
                err = str(j.get("error", "")) or str(j.get("message", ""))
            raw = repr(j)[:300]
            logging.warning("place_post_only gagal (oid kosong) %s %s px=%s qty=%s err=%r raw=%s",
                            pair, side, px_str, qty_str, err[:120], raw)
            return Order(oid="0", pair=pair, side=side, price=price, qty=qty,
                        ts=time.time(), filled=D(0))  # AUDIT 29-Sep: order GAGAL
                        # terpasang TIDAK boleh mengaku terisi (dulu filled=qty = fail-open;
                        # semua pemanggil memeriksa oid dulu, tapi ini jebakan utk kode baru).  # marked filled → langsung dibuang

        return Order(oid=str(oid), pair=pair, side=side, price=price, qty=qty,
                    ts=time.time(), cl_ord_id=str(cl_id))

    def place_market_ioc(self, pair: str, side: str, qty: Decimal, ref_px: Decimal,
                         reduce_only: bool = False) -> Order:
        """Market IOC order — fill TERJAMIN (perps). DITEMUKAN 2026-06-21: limit-GTC
        di touch perps SoDEX → oid=0 (crossing ditolak), TAPI market+IOC terisi andal
        (terbukti tutup ENA orphan). ref_px hanya utk format qty (presisi).
        reduce_only=True utk menutup posisi."""
        if side not in self._SIDES:
            raise ValueError(f"side invalid: {side}")
        is_perp = "-USD" in pair.upper()
        market = "perps" if is_perp else "spot"
        p = ref_px
        if p < D("1"):
            qty_str = str(int(float(qty)))
        elif p < D("10"):
            qty_str = f"{float(qty):.4f}"
        elif p < D("10000"):
            qty_str = f"{float(qty):.5f}"
        else:
            qty_str = f"{float(qty):.6f}"
        args = ["orders", "place", market, "--symbol", pair, "--side", side,
                "--qty", qty_str, "--type", "market", "--tif", "ioc", "--format", "json"]
        if reduce_only and is_perp:
            args.insert(-2, "--reduce-only")
        j = self._sodex(args, timeout=30)
        oid = ""
        if isinstance(j, dict):
            for k in ("orderID", "orderId", "order_id", "id"):
                v = j.get(k)
                if v not in (None, 0, "0", ""):
                    oid = str(v); break
        if not oid:
            logging.warning("place_market_ioc gagal %s %s qty=%s reduce=%s raw=%s",
                            pair, side, qty_str, reduce_only, repr(j)[:200])
            return Order(oid="0", pair=pair, side=side, price=ref_px, qty=qty,
                        ts=time.time(), filled=D(0))  # AUDIT 29-Sep: order GAGAL
                        # terpasang TIDAK boleh mengaku terisi (dulu filled=qty = fail-open;
                        # semua pemanggil memeriksa oid dulu, tapi ini jebakan utk kode baru).
        # Market IOC terisi seketika → tandai filled penuh (skip poll yg di-neuter B9)
        return Order(oid=str(oid), pair=pair, side=side, price=ref_px, qty=qty,
                    ts=time.time(), filled=qty, cl_ord_id=str(j.get("clOrdID", "")))

    def place_limit_ioc_perp(self, perp: str, side: str, qty: Decimal, price: Decimal) -> Order:
        """Limit-IOC untuk perp open: sell di bid → langsung cross sebagai taker.
        Fallback dari market-IOC yang reject new-open positions (oid=0 pada 1000PEPE-USD dll)."""
        p = price
        if p < D("1"):
            qty_str = str(int(float(qty)))
            px_str = f"{float(p):.6f}"      # PEPE 0.002846 → "0.002846"
        elif p < D("10"):
            qty_str = f"{float(qty):.4f}"
            px_str = f"{float(p):.3f}"
        elif p < D("10000"):
            qty_str = f"{float(qty):.5f}"
            px_str = f"{float(p):.2f}"
        else:
            qty_str = f"{float(qty):.6f}"
            px_str = f"{float(p):.2f}"
        j = self._sodex([
            "orders", "place", "perps",
            "--symbol", perp, "--side", side,
            "--price", px_str, "--qty", qty_str,
            "--type", "limit", "--tif", "ioc",
            "--format", "json"], timeout=30)
        oid = ""
        if isinstance(j, dict):
            for k in ("orderID", "orderId", "order_id", "id"):
                v = j.get(k)
                if v not in (None, 0, "0", ""):
                    oid = str(v); break
        if not oid:
            logging.warning("place_limit_ioc_perp gagal %s %s px=%s qty=%s raw=%s",
                           perp, side, px_str, qty_str, repr(j)[:200])
            return Order(oid="0", pair=perp, side=side, price=price, qty=qty,
                        ts=time.time(), filled=D(0))  # AUDIT 29-Sep: order GAGAL
                        # terpasang TIDAK boleh mengaku terisi (dulu filled=qty = fail-open;
                        # semua pemanggil memeriksa oid dulu, tapi ini jebakan utk kode baru).
        return Order(oid=str(oid), pair=perp, side=side, price=price, qty=qty,
                    ts=time.time(), filled=qty, cl_ord_id=str(j.get("clOrdID", "")))

    def cancel(self, order: Order):
        """Cancel order. SPOT: butuh --symbol-id, --order-id, DAN --cl-ord-id.
        PERPS: butuh --symbol-id dan --order-id SAJA (tanpa cl-ord-id)."""
        # Skip phantom orders (failed placement: oid="0", cl_ord_id kosong)
        if not order.oid or order.oid == "0":
            return
        is_perp = "-USD" in order.pair.upper()
        market = "perps" if is_perp else "spot"
        sid = self._sym_id(order.pair)
        if sid is None:
            logging.warning("cancel: symbol-id tidak dikenal utk %s — dilewati", order.pair)
            return
        
        # SOLEX v2: SPOT butuh BOTH order-id DAN cl-ord-id; PERPS hanya order-id
        cl_id = order.cl_ord_id or f"sodex-twin-{int(time.time())}"
        args = [
            "orders", "cancel", market,
            "--symbol-id", str(sid),
            "--order-id", str(order.oid),
            "--format", "json",
        ]
        if not is_perp:
            # SPOT: cl-ord-id required
            args.insert(-2, "--cl-ord-id")
            args.insert(-2, str(cl_id))

        self._sodex(args, timeout=15)
    
    def cancel_all_spot_orders(self) -> int:
        """Cancel SEMUA order spot terbuka di exchange (dipanggil saat startup).
        Mengembalikan jumlah order yang berhasil di-cancel.
        Penting: mencegah orphaned orders setelah restart engine."""
        orders = self._sodex_list(["orders", "list", "spot", "--format", "json"], timeout=15)
        cancelled = 0
        for o in orders:
            oid = str(o.get("orderID", ""))
            cl_id = str(o.get("clOrdID", ""))
            sym = o.get("symbol", "")
            # Tentukan symbol-id dari nama symbol
            sid = None
            for pair, pair_sid in self._SYMBOL_MAP.items():
                # SoDEX symbol format: vPEPE_vUSDC — cek BASE currency saja
                base = pair.split("/")[0].upper()
                if pair_sid and base in sym.upper():
                    sid = pair_sid; break
            if not oid or not cl_id or sid is None:
                logging.warning("cancel_all: skip order tanpa oid/cl_id/sid: %s", o)
                continue
            self._sodex([
                "orders", "cancel", "spot",
                "--symbol-id", str(sid),
                "--order-id", oid,
                "--cl-ord-id", cl_id,
                "--format", "json",
            ], timeout=15)
            cancelled += 1
        return cancelled

    def sweep_perps_ghosts(self) -> int:
        """Startup: deteksi & bersihkan ghost positions di SEMUA perps symbols.
        Menggunakan orderbook REAL untuk menentukan harga penutupan.
        Returns jumlah ghost yang berhasil di-sweep.

        DETECTION: Conservative — only sweeps on explicit "open positions" error.
        Empty/inconclusive API responses are SKIPPED to prevent false positives
        (falsely closing a real position would be far worse than missing a ghost).
        """
        swept = 0
        perps_pairs = [k for k in self._SYMBOL_MAP if "-USD" in k]
        for pair in perps_pairs:
            sid = self._sym_id(pair)
            if not sid:
                continue
            # Cek leverage — jika gagal dengan "open positions", ada ghost.
            # PENTING: empty/exception → SKIP (jangan sweep: false positive bahaya)
            try:
                j = self._sodex(["leverage", pair, "5", "--format", "json"], timeout=10)
                # Harus dict non-kosong dan mengandung error "open positions"
                if not isinstance(j, dict) or not j:
                    logging.debug("ghost_check %s: response kosong/tidak valid — skip", pair)
                    continue
                err = str(j.get("error", "")) + str(j.get("message", ""))
                if "open positions" not in err.lower():
                    continue  # no ghost confirmed
            except Exception as e:
                logging.debug("ghost_check %s: exception — skip: %s", pair, e)
                continue  # exception → inconclusive → skip conservatively
            
            logging.warning("👻 GHOST detected on %s — getting real price...", pair)
            
            # Dapatkan orderbook REAL untuk harga
            try:
                bk_j = self._sodex(["orderbook", "perps", pair, "--depth", "1", "--format", "json"], timeout=10)
                if not bk_j or "bids" not in bk_j or "asks" not in bk_j or not bk_j["bids"] or not bk_j["asks"]:
                    logging.error("👻 Cannot get orderbook for %s — skip", pair)
                    continue
                bid_px = float(bk_j["bids"][0]["price"])
                ask_px = float(bk_j["asks"][0]["price"])
                # Buy at 0.2% above ask (aggressive taker), sell at 0.2% below bid
                buy_price = f"{ask_px * 1.002:.4f}"
                sell_price = f"{bid_px * 0.998:.4f}"
            except Exception:
                logging.error("👻 Orderbook parse error for %s", pair)
                continue
            
            # Coba tutup: buy (close short) lalu sell (close long)
            for side, price, sizes in [
                ("buy", buy_price, [50, 100, 500, 1000]),
                ("sell", sell_price, [50, 100, 500, 1000]),
            ]:
                for qty in sizes:
                    r = self._sodex([
                        "orders", "place", "perps",
                        "--symbol", pair,
                        "--side", side,
                        "--price", price,
                        "--qty", str(qty),
                        "--type", "limit",
                        "--reduce-only",
                        "--format", "json",
                    ], timeout=15)
                    oid = r.get("orderID", 0) if isinstance(r, dict) else (r[0].get("orderID", 0) if isinstance(r, list) and r else 0)
                    if oid and int(oid) > 0:
                        swept += 1
                        logging.info("👻 Ghost sweep %s %s %s @%s — OID=%s", pair, side, qty, price, oid)
                        time.sleep(2)
                        # Cek apakah ghost sudah bersih
                        j2 = self._sodex(["leverage", pair, "5", "--format", "json"], timeout=10)
                        err2 = str(j2.get("error", "")) + str(j2.get("message", ""))
                        if "open positions" not in err2.lower():
                            logging.info("✅ GHOST %s CLEARED", pair)
                            break  # keluar dari loop ukuran
                    time.sleep(0.3)
                else:
                    continue
                break  # ghost cleared
            
            # Verifikasi final
            time.sleep(1)
            j3 = self._sodex(["leverage", pair, "5", "--format", "json"], timeout=10)
            err3 = str(j3.get("error", "")) + str(j3.get("message", ""))
            if "open positions" in err3.lower():
                logging.error("👻 GHOST %s PERSISTS after sweep — backend bug!", pair)
            else:
                logging.info("✅ GHOST %s VERIFIED CLEAN", pair)
        return swept

    def poll_fill(self, order: Order) -> Decimal:
        """Cek status order — gunakan _poll_cache jika ada DAN scope market
        cocok, jika tidak fallback ke list. S1 fix (audit 06-Okt-2026): lihat
        catatan di step() -- cache lintas-market/stale TIDAK dipercaya."""
        # Gunakan cache dari step() jika tersedia DAN market-nya cocok
        cache = getattr(self, '_poll_cache', None)
        cache_market = getattr(self, '_poll_cache_market', None)
        order_market = "perps" if "-USD" in order.pair.upper() else "spot"
        if cache is not None and cache_market == order_market:
            total_filled = D(str(cache.get(str(order.oid), {}).get("executedQty", 0)))
            inc = max(D(0), total_filled - order.filled)
            order.filled = total_filled
            return inc
        
        # Fallback: panggil langsung (untuk non-batch usage) — pakai _sodex_list
        is_perp = "-USD" in order.pair.upper()
        market = "perps" if is_perp else "spot"

        orders = self._sodex_list(["orders", "list", market, "--format", "json"], timeout=15)

        for o in orders:
            oid = str(o.get("orderID", ""))
            if oid == str(order.oid):
                total_filled = D(str(o.get("executedQty", 0)))
                inc = max(D(0), total_filled - order.filled)
                order.filled = total_filled
                return inc

        # B9 FIX: Order tidak ditemukan di open-list.
        # SoDEX CLI HANYA punya {cancel, list, place} — TIDAK ada order
        # history/status, jadi kita TIDAK BISA memverifikasi apakah order ini
        # terisi atau dibatalkan/ditolak/expired.
        # KODE LAMA mengasumsikan "terisi penuh" → ini menyebabkan PHANTOM FILL:
        #   - flush-sell ditolak (post-only nyebrang) → hilang dari list
        #   - poll_fill lapor "terisi" → tracker kira inventori terjual
        #   - INV SYNC baca balance riil → koreksi balik → THRASHING ABADI
        #   - ledger tercemar fill + RT palsu dengan PnL palsu
        # FIX AMAN: asumsikan TIDAK terisi (return 0). Order yang hilang jauh
        # lebih sering karena ditolak daripada terisi diam-diam. Kebenaran
        # inventori datang dari _sync_inventory_from_exchange() yang membaca
        # `balance spot` riil (terbukti stabil & konsisten). Fill nyata tetap
        # tertangkap via executedQty selagi order masih di list/cache (di atas).
        if order.filled < order.qty:
            logging.warning(
                "poll_fill: order %s hilang dari open-list — asumsi TIDAK terisi "
                "(kebenaran inventori dari balance-sync); sisa %s qty tidak dihitung fill",
                order.oid, order.qty - order.filled)
        return D(0)
    
    def funding_rate(self, pair: str) -> Decimal:
        """Get funding rate (PERPS only). SoDEX v2: dari tickers perps."""
        try:
            tickers = self._sodex_list(["tickers", "perps", "--format", "json"], timeout=10)
            for t in tickers:
                if t.get("symbol") == pair:
                    return D(str(t.get("fundingRate", 0)))
            return D(0)
        except Exception:
            return D(0)

# ============================== 6. GUARDS & GATES ============================

class HardStop(Exception): pass

class Guards:
    """Lapisan pelindung independen — selalu menang atas strategi (R1..R7, G4)."""
    def __init__(self, cfg: Config, led: Ledger, tg: Telegram):
        self.cfg, self.led, self.tg = cfg, led, tg
        if led.get_state("equity_high", "0") == 0:
            led.set_state("equity_high", cfg.capital_usd)
    def _today_iso(self):
        return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    def in_event_window(self) -> bool:
        now = datetime.now(UTC)
        return any(a <= now <= b for a, b in self.cfg.event_guard_windows())
    def check_equity(self, equity, source: str = "ledger"):
        """G4 drawdown guard. G4 FIX 2026-09-27: ratchet anti-campur-sumber —
        equity_high hanya boleh dibandingkan dengan angka dari SUMBER yang sama.
        Saat sumber berganti (mis. ledger $66,15 → live_account $61,63) anchor
        di-RE-ANCHOR ke nilai baru, bukan dihitung drawdown silang sumber yang
        tidak sebanding (akar crash-loop 48× restart 26-Sep)."""
        if equity is None:
            # S2 fix (audit 06-Okt-2026): fail-SKIP dipertahankan sengaja
            # (fail-closed sempat sebabkan crash-loop 48× restart 26-Sep saat
            # baca equity sesaat gagal) -- tapi kini VISIBLE: alert sekali
            # per ambang beruntun, bukan diam total tanpa jejak operasional.
            n = int(self.led.get_state("equity_skip_streak", "0")) + 1
            self.led.set_state("equity_skip_streak", n)
            if n in (3, 10, 30):
                self.tg.send(f"⚠️ G4: equity ({source}) tak terbaca {n}× beruntun — "
                              f"drawdown guard SKIP (bukan HALT). Cek account_equity().")
            return  # live & akun tak terbaca → skip (fail-SKIP, bukan fail-STOP
                    # dengan angka salah; B13/monitor tetap memfoto kondisi riil)
        self.led.set_state("equity_skip_streak", 0)
        prev_src = self.led.get_state_text("equity_high_source")
        hi = self.led.get_state("equity_high")
        if prev_src != source or hi <= 0:
            self.led.set_state("equity_high", equity)
            self.led.set_state_text("equity_high_source", source)
            hi = equity
        else:
            hi = max(hi, equity)
            self.led.set_state("equity_high", hi)
        if hi > 0 and (hi - equity) / hi >= self.cfg.drawdown_stop_frac:
            self.tg.send(f"🛑 G4 DRAWDOWN ≥{self.cfg.drawdown_stop_frac:.0%} — HARD STOP")
            # AUDIT 29-Sep-2026: tulis penanda fail-closed. Sebelumnya write_safety_halt
            # hanya DIDEFINISIKAN, tak pernah dipanggil → komponen lain yang menggate pada
            # data/SAFETY_HALT tidak tahu hard-stop terjadi = fail-OPEN di rantai safety.
            # Ini MEMPERKUAT fail-closed (bukan melonggarkan ambang/kill-switch).
            write_safety_halt("g4_drawdown",
                              drawdown_frac=float((hi - equity) / hi),
                              equity=float(equity), equity_high=float(hi))
            raise HardStop("drawdown")
        day_pnl = self.led.e1_profit_since(self._today_iso())
        if day_pnl < -self.cfg.daily_loss_limit:
            self.tg.send(f"🛑 Loss harian {day_pnl:.2f} USD melewati limit — stop hari ini")
            write_safety_halt("daily_loss_limit", day_pnl=float(day_pnl),
                              limit=float(self.cfg.daily_loss_limit))
            raise HardStop("daily-loss")
    def principal_fee_ok(self, extra_fee: Decimal) -> bool:
        spent = self.led.get_state("principal_fee_spent")
        if spent + extra_fee > self.cfg.principal_fee_cap:
            return False
        return True
    def spend_principal_fee(self, fee: Decimal):
        self.led.set_state("principal_fee_spent",
                           self.led.get_state("principal_fee_spent") + fee)

class Treasury:
    """G6: kapasitas Engine-2 = profit terealisasi E1 7 hari terakhir
            − fee E2 minggu poin berjalan, ditambah sisa jatah kalibrasi pokok."""
    def __init__(self, cfg: Config, led: Ledger, guards: Guards):
        self.cfg, self.led, self.g = cfg, led, guards
    def allowance(self) -> Decimal:
        wk = week_start_iso()
        e1 = self.led.e1_profit_since((datetime.now(UTC) - timedelta(days=7)).isoformat())
        e2_spent = self.led.fees_since(wk, engine="E2")
        subsidi = max(D(0), e1) - e2_spent
        kalibrasi = max(D(0), self.cfg.principal_fee_cap
                        - self.led.get_state("principal_fee_spent"))
        return subsidi + kalibrasi
    def authorize(self, est_fee: Decimal) -> bool:
        if est_fee <= max(D(0), self.allowance()):
            return True
        return False

# ============================== 7. ENGINE-1 FLYWHEEL =========================

def oid0_backoff_s(streak: int) -> int:
    """B60 (29-Sep-2026): ladder backoff untuk retry post-only yang DITOLAK (oid=0).

    Akar kebocoran −$8,6/hari: cooldown tetap 5s → 12 retry/menit/sisi selama berjam-jam.
    streak 0-1 → 5s (normal) · 2-3 → 30s · 4-5 → 180s · 6-9 → 600s · ≥10 → 1800s (karantina sisi).
    Diekstrak jadi fungsi murni agar bisa diuji langsung.
    """
    if streak >= 10:
        return 1800
    if streak <= 1:
        return 5
    return min(5 * (6 ** min(streak // 2, 3)), 600)


class Engine1Flywheel:
    """Spot MM dua-sisi: quote bid+ask acak di dalam spread, pasangkan fill
    menjadi RT, hitung net%/RT, ramp size via G2, hedge delta via perp bila ada.
    
    Fase 1 — 4 perbaikan inventori (Fable §3.3):
      1. Inventory cap per-pair kecil ($25, bukan $60)
      2. Skew quoting saat inv > 50% cap → dorong ke netral
      3. Flush rule: inv > 30 menit → jual ke bid (bayar taker)
      4. Akhir sesi WAJIB flat — tidak ada inventori menginap
    """
    def __init__(self, cfg, adapter, led, guards, tg, hedge_enabled: bool, pair: str | None = None):
        self.cfg, self.x, self.led, self.g, self.tg = cfg, adapter, led, guards, tg
        self.hedge = hedge_enabled
        self.pair = pair or cfg.spot_pair  # override utk pair kedua
        self.ladder_i = 0
        self.orders: list[Order] = []
        self.inv_qty = D(0)            # inventori bersih (spot)
        _hkey = f"hedge_qty_{(pair or cfg.spot_pair).replace('/', '_')}"
        self.hedge_qty = self.led.get_state(_hkey, "0")   # restore across restarts
        self._hedge_qty_key = _hkey    # cache key for saves in _rebalance_hedge
        # Regime-adaptive hedge state
        self._regime = RegimeDetector(window=cfg.e1_regime_window,
                                      bull_thr=float(cfg.e1_regime_thr),
                                      bear_thr=float(cfg.e1_regime_thr))
        self._regime_label = "NEUTRAL"
        self._regime_cache_ts = 0.0
        self._last_hedge_tg = 0.0
        self.buy_q: list[tuple] = []   # (price, qty) FIFO utk pairing RT
        # Seed dari ledger (BUKAN 0): ID RT wajib monotonik lintas restart — kalau
        # mulai dari 0, ID lama dipakai ulang dan baris historis tertimpa
        # (insiden 28-Sep-2026: 319 baris tertimpa, metrik window jadi artefak).
        self._rt = self.led.next_rt_seq("E1")
        self._inv_started: float | None = None  # epoch saat inventori pertama non-zero
        self._last_skew_warn = 0.0
        self._last_quote_diag_log = 0.0
        self._hedge_lev_set: set[str] = set()   # perps yg sudah di-set leverage (hedge)
        self._last_place_skip_reason = ""
        # B13: bila True, fill/inventori di-rekonsiliasi dari saldo riil
        # (poll_fill TIDAK mencatat fill → cegah double-count). Di-set live oleh
        # orchestrator. Paper/selftest tetap pakai jalur poll_fill lama.
        self.reconcile_mode = False
        # B14: gate profitabilitas — True = pause pasang quote baru (EV negatif).
        self._quoting_paused = False
        self._last_gate_log = 0.0
        # B35: pulihkan state PAUSE lintas restart daemon.
        # Bila pause key > 0 di DB, engine sudah PAUSE sebelum mati →
        # set _quoting_paused=True WITHOUT menulis ulang timestamp (preserving original).
        # Tanpa ini: restart selalu reset timer → B31 tidak pernah fire, stuck capital
        # tidak terdeteksi secara jujur.
        # B43: state pause wajib pair-scoped. Legacy key global tetap hanya untuk
        # spot_pair utama; jika tidak, pause PEPE membekukan SHIB/E1b tanpa sampel RT.
        # isinstance guard: real Ledger.get_state() kembalikan str atau Decimal;
        # MagicMock test doubles kembalikan MagicMock → skip (aman di unit tests).
        try:
            _pause_ts_raw = led.get_state(self._b14_pause_key())
            if isinstance(_pause_ts_raw, (str, Decimal)) and float(_pause_ts_raw) > 0:
                self._quoting_paused = True
        except (TypeError, ValueError):
            pass
        # B40: non-blocking flush state (mencegah 120s block yang membekukan SHIB/E1b)
        self._last_flush_ts = 0.0   # epoch flush terakhir (cooldown 5 menit)
        self._flushing = False       # True = flush order aktif → tahan buy baru
        # B43: cooldown per sisi setelah oid=0 — cegah spam retry ke exchange
        self._oid0_ts: dict[str, float] = {"buy": 0.0, "sell": 0.0}
        # B60 (29-Sep-2026): backoff eksponensial + karantina sisi.
        # Akar kebocoran −$8,6/hari: cooldown TETAP 5s → 12 retry/menit/sisi berjam-jam
        # (≈2.900 trade venue/hari, capture negatif) sementara post-only terus ditolak.
        self._oid0_streak: dict[str, int] = {"buy": 0, "sell": 0}
    
    # ── helper ──
    def _inv_usd(self, mid: Decimal) -> Decimal:
        return abs(self.inv_qty) * mid

    def _min_spread(self) -> Decimal:
        # Pair-1 (PEPE) pakai gate ketat e1_min_spread (spread lebar 0.35%).
        # Pair sekunder (SHIB, XLM, dst) pakai gate lebih rendah e1_pair2_min_spread
        # agar pair spread-sedang (XLM 0.141%) bisa quote (tetap > fee → profit).
        if self.pair == self.cfg.spot_pair:
            return self.cfg.e1_min_spread
        return self.cfg.e1_pair2_min_spread

    def _b14_pause_key(self) -> str:
        if self.pair == self.cfg.spot_pair:
            return "b14_pause_since_ts"
        return f"b14_pause_since_ts:{self.pair}"

    def _inv_started_key(self) -> str:
        if self.pair == self.cfg.spot_pair:
            return "e1_inv_started_ts"
        return f"e1_inv_started_ts:{self.pair}"

    def _inv_age_minutes(self) -> float:
        if self._inv_started is None or self.inv_qty == 0:
            return 0.0
        return (time.time() - self._inv_started) / 60.0

    def _restore_inv_started(self) -> bool:
        """Restore timestamp inventori dari DB untuk pair ini."""
        try:
            saved_ts = self.led.get_state(self._inv_started_key())
            if isinstance(saved_ts, (str, Decimal)) and float(saved_ts) > 0:
                self._inv_started = float(saved_ts)
                return True
        except (TypeError, ValueError):
            pass
        return False

    def _set_inv_started(self, ts: float | None):
        """B37: set _inv_started DAN simpan ke DB (tahan lintas restart).

        Semua assignments _inv_started harus lewat sini agar timestamp
        persisten. Saat restart, seed_baseline() membaca DB dan menggunakan
        timestamp lama — sehingga B36 age > 4h dihitung dari kapan inventori
        BENAR-BENAR masuk, bukan dari kapan daemon di-restart.

        B45: key timestamp wajib pair-scoped. Jika SHIB memakai key global PEPE,
        inventori baru SHIB bisa langsung dianggap tua dan ter-flush prematur.
        """
        self._inv_started = ts
        try:
            self.led.set_state(self._inv_started_key(), str(ts or 0))
        except Exception:
            pass
    
    # ── kuotasi dengan skew (perbaikan #2) ──
    SODEX_MIN_NOTIONAL = D("5.0")  # SoDEX minimum notional per order (Jun 2026)
    
    def _quote_size_usd(self) -> Decimal:
        base = self.cfg.e1_size_ladder[self.ladder_i]
        usd = base * D(str(RNG.uniform(0.6, 1.4)))
        # Hard floor: SoDEX rejects orders below $5 notional
        if usd < self.SODEX_MIN_NOTIONAL:
            usd = self.SODEX_MIN_NOTIONAL * D(str(RNG.uniform(1.0, 1.3)))
        return usd
    
    def _place_two_sided(self, bk: Book, aggressive: int = 0):
        """Place maker orders. aggressive=0: pure maker (DEFAULT — spread capture).
        aggressive=1: mid-spread. aggressive=2: near-taker (max volume, NO edge).

        DEFAULT aggressive=0 (B-fix 2026-06-17): E1 adalah MESIN PROFIT (flywheel
        maker), bukan mesin volume. aggressive=2 (near-taker) lama MENYEBERANG
        spread → bayar ~taker, TIDAK capture spread, dan fill instan lalu lenyap
        sebelum poll menangkapnya (pasca-fix B9 → tak terekam) → thrashing +
        ledger buta. Pure maker (rest dekat touch) capture spread penuh (~0.29%/RT
        net setelah fee di PEPE), fill terekam via poll/cross-check, volume MAKER
        untuk SoPoints. Mesin VOLUME adalah E2 (perps churn), bukan E1."""
        spr_abs = bk.ask - bk.bid
        inv_frac = float(self._inv_usd(bk.mid) / self.cfg.e1_inv_cap_per_pair) if self.cfg.e1_inv_cap_per_pair > 0 else 0
        
        # ── PRIORITASKAN sisi pembuangan inventori ──
        if self.inv_qty > 0:
            sides = ("sell", "buy")  # long: jual dulu baru beli
        else:
            sides = ("buy", "sell")  # short: beli dulu baru jual
        
        # Aggressive depth: 0=pure maker, 1=mid, 2=near-taker
        depth_map = {0: (0.05, 0.35), 1: (0.35, 0.65), 2: (0.65, 0.95)}
        d_min, d_max = depth_map.get(aggressive, (0.65, 0.95))
        placed = 0
        skip_reasons: list[str] = []
        
        for side in sides:
            # B60 (29-Sep-2026): backoff ADAPTIF mengikuti streak reject (lihat oid0_backoff_s).
            _streak = self._oid0_streak.get(side, 0)
            _backoff = oid0_backoff_s(_streak)
            if time.time() - self._oid0_ts.get(side, 0.0) < _backoff:
                skip_reasons.append(f"{side}_oid0_cooldown{int(_backoff)}s(streak={_streak})")
                continue
            depth = D(str(RNG.uniform(d_min, d_max)))
            px = (bk.bid + spr_abs * depth) if side == "buy" else (bk.ask - spr_abs * depth)
            # B61 (29-Sep-2026, terbukti live 00:52): post-only TIDAK BOLEH menyentuh/
            # menembus sisi lawan. Pada spread ~1 tick, `ask − spr×depth` jatuh ≤ best bid →
            # venue menolak SELL post-only (oid=0) → HANYA BUY terisi → inventori menumpuk
            # (4,5jt PEPE / $19) = adverse inventory. Perlakuan sama dgn temuan Juni utk flush:
            # SELL aman di ask + fraksi spread (di luar touch), BUY simetris.
            _exp = bk.bid.as_tuple().exponent            # presisi buku (int untuk harga normal)
            _tick = D(1).scaleb(_exp) if isinstance(_exp, int) else D("0.00000001")
            _edge = max(spr_abs * D("0.05"), _tick)
            # Temuan Juni + bukti live 00:52-00:57: pada spread 1 TICK, `spr×0,05` < 1 tick
            # sehingga harga tetap mentok di touch → venue menolak (oid=0) dan hanya satu sisi
            # yang terisi. Karena itu edge minimal = 1 tick nyata.
            # Aturan venue: SELL strict di atas ask; BUY strict di bawah bid.
            if side == "sell" and px <= bk.ask:
                px = bk.ask + _edge
            elif side == "buy" and px >= bk.bid:
                px = bk.bid - _edge
            if px <= 0:
                skip_reasons.append(f"{side}_px_invalid")
                continue

            # ── SKEW: saat inventory > skew_frac × cap, geser quote searah pembuangan ──
            if inv_frac > float(self.cfg.e1_inv_skew_frac):
                skew = D(str(inv_frac - float(self.cfg.e1_inv_skew_frac))) * spr_abs
                if self.inv_qty > 0:
                    px -= skew  # long: turunkan semua quote → jual lebih agresif, beli lebih konservatif
                else:
                    px += skew  # short: naikkan semua quote → beli lebih agresif, jual lebih konservatif
                if time.time() - self._last_skew_warn > 300:
                    self.tg.send(f"⚠️ SKEW aktif: inv {inv_frac:.0%} cap → bias quote")
                    self._last_skew_warn = time.time()

            # B47: crossing-clamp — skew ekstrem dapat push px melewati spread
            # B50: inside-spread clamp — pada 1-tick spread (PEPE/SHIB), harga antara bid/ask
            #      bukan price level yang valid → exchange tolak sebagai taker (oid=0).
            # B61 (audit live 29-Sep-2026): clamp WAJIB tetap di LUAR touch, bukan di touch.
            #      Bukti venue: post-only sell TEPAT di ask & buy TEPAT di bid → oid=0
            #      (hanya satu sisi terisi → inventori adverse 4,5jt PEPE). Karena itu
            #      clamp memakai _edge (≥1 tick), bukan ask/bid polos — menyatukan
            #      B47/B50 (jangan menembus spread) dengan B61 (jangan menyentuh touch).
            if side == "sell" and px < bk.ask + _edge:   # B47+B50+B61
                px = bk.ask + _edge
            elif side == "buy" and px > bk.bid - _edge:  # B47+B50+B61
                px = bk.bid - _edge

            # B53: cancel opposite resting orders that would self-cross the new
            # maker price. Do this before sizing checks too: even if a dust sell
            # is skipped, a stale crossing buy can still poison the next quote.
            #
            # B62 (audit 29-Sep-2026, bukti live): buang JUGA order SISI-SAMA pada
            # harga lama. Sebelumnya hanya sisi berlawanan yang dibatalkan → setiap
            # siklus menambah BUY baru tanpa membuang yang lama → 4 BUY menumpuk
            # (exposure ~$20 vs cap inventori $10). Karena kuota quoting berbunyi
            # `len(self.orders) < 4`, tumpukan itu MENGUNCI kuota → sisi SELL tidak
            # pernah dipasang → inventori tidak pernah ternetralkan (akar satu-sisi).
            for ro in list(self.orders):
                if ro.pair != self.pair:
                    continue
                crosses = (side == "sell" and ro.side == "buy" and ro.price >= px) or \
                          (side == "buy" and ro.side == "sell" and ro.price <= px)
                # B62: order SISI-SAMA pada harga lama sengaja TIDAK dibatalkan
                # (menjaga queue priority maker) — dicegah oleh guard idempoten di bawah.
                if crosses:
                    try:
                        self.x.cancel(ro)
                    except Exception:
                        pass
                    if ro in self.orders:
                        self.orders.remove(ro)
            
            # B62 (audit 29-Sep-2026, bukti live): IDEMPOTEN — jangan tambah quote
            # yang sudah punya order SISI-SAMA aktif. Sebelumnya setiap siklus menambah
            # BUY baru tanpa membuang yang lama → 4 BUY menumpuk (exposure ~$20 vs cap
            # inventori $10) dan kuota `len(self.orders) < 4` MENGUNCI sisi SELL →
            # inventori tidak pernah ternetralkan. Order lama SENGAJA tidak dibatalkan
            # (B53: churn = kehilangan queue priority maker); cukup tahan diri.
            if any(ro for ro in self.orders if ro.pair == self.pair and ro.side == side):
                skip_reasons.append(f"already_quoted_{side}")
                continue

            usd = self._quote_size_usd()
            qty = usd / px
            
            # ── cap inventori per-pair (perbaikan #1) — LEBIH KETAT ──
            if side == "buy":
                proj = (self.inv_qty + qty) * bk.mid
                if proj > self.cfg.e1_inv_cap_per_pair * D("0.85"):  # 85% cap untuk beli
                    # BUGFIX audit 2026-09-27 (deadlock E1, 0 order >6 jam):
                    # inv dust ($4.90 < min notional $5) → sell B45 skip SELAMANYA;
                    # buy ≥$5 selalu proj>$8.50 → skip. Engine beku total.
                    # Escape: bila inventori terkunci dust, naikkan beli seadanya
                    # sampai cap penuh (bukan 85%) supaya sell ≥$5 valid lagi.
                    inv_usd_now = self.inv_qty * bk.mid
                    dust_locked = D("0") < self.inv_qty and inv_usd_now < self.SODEX_MIN_NOTIONAL
                    cap_now = self.cfg.e1_inv_cap_per_pair if dust_locked else self.cfg.e1_inv_cap_per_pair * D("0.85")
                    if proj <= cap_now:
                        pass  # dust-escape: izinkan quote ini
                    else:
                        skip_reasons.append(
                            f"buy_cap proj={proj:.4f} limit={cap_now:.4f}")
                        continue
            else:  # sell
                proj = (self.inv_qty - qty) * bk.mid
                if proj < -self.cfg.e1_inv_cap_per_pair * D("0.85"):
                    skip_reasons.append(
                        f"sell_cap proj={proj:.4f} limit={(-self.cfg.e1_inv_cap_per_pair * D('0.85')):.4f}")
                    continue
                # B45: jika inv_qty < quote_qty tapi masih >= min_notional, jual semua sisa
                if self.inv_qty < qty:
                    inv_usd = self.inv_qty * bk.mid
                    if inv_usd >= self.SODEX_MIN_NOTIONAL:
                        qty = self.inv_qty  # jual sisa penuh
                    else:
                        skip_reasons.append(
                            f"sell_insufficient inv={self.inv_qty:.0f} qty={qty:.0f} inv_usd={inv_usd:.2f}")
                        continue

            o = self.x.place_post_only(self.pair, side, px, qty)
            if o.oid and o.oid != "0":   # hanya track order yang berhasil dipasang
                self.orders.append(o)
                placed += 1
                self._oid0_streak[side] = 0          # B60: sukses → reset backoff
            else:
                self._oid0_ts[side] = time.time()
                _st = self._oid0_streak.get(side, 0) + 1
                self._oid0_streak[side] = _st
                if _st in (10, 30):                  # alert SEKALI per ambang, bukan spam per retry
                    self.tg.send(f"🚧 {self.pair} {side}: {_st}× reject beruntun (oid=0) — "
                                 f"backoff {'30 menit' if _st >= 10 else '10 menit'}. "
                                 f"Periksa: pair active / notional minimum / harga stale.")
                skip_reasons.append(f"{side}_oid0")
        self._last_place_skip_reason = "; ".join(skip_reasons)
        return placed
    
    # ── fill & RT accounting ──
    def _on_fill(self, o: Order, inc: Decimal):
        fee = o.price * inc * self.cfg.spot_maker_fee
        rt_id = None
        
        # Track inventory start time
        if self.inv_qty == 0:
            self._set_inv_started(time.time())

        if o.side == "buy":
            self.inv_qty += inc
            self.buy_q.append((o.price, inc))
        else:
            self.inv_qty -= inc
            remain = inc
            while remain > 0 and self.buy_q:
                bpx, bq = self.buy_q[0]
                take = min(bq, remain)
                self._rt += 1
                rt_id = f"E1-{self._rt}"
                vol = (bpx + o.price) * take
                pnl = (o.price - bpx) * take - vol * self.cfg.spot_maker_fee
                self.led.rt_close(rt_id, "E1", o.pair, vol, pnl)
                if take == bq: self.buy_q.pop(0)
                else: self.buy_q[0] = (bpx, bq - take)
                remain -= take
        
        # Reset timer if flat
        if self.inv_qty == 0:
            self._set_inv_started(None)
        
        self.led.fill("E1", "S", o.pair, o.side, o.price, inc, fee, True, rt_id)

    # ── B13: AKUNTING BERBASIS BALANCE-DELTA (kebenaran tunggal) ──
    RECONCILE_DUST_USD = D("0.10")  # abaikan delta < $0.10 (debu/pembulatan)

    def reconcile_delta(self, real_qty: Decimal, mid: Decimal,
                        d_usdc_signed: Decimal | None) -> dict | None:
        """Rekonsiliasi inventori dari SALDO RIIL (bukan deteksi order).

        SoDEX CLI tanpa order-history → fill yang lenyap antar-poll tak bisa
        direkam andal (B9). Solusi: derive fill dari DELTA saldo riil — saldo
        adalah satu-satunya kebenaran. Fee otomatis ter-bake bila d_usdc tersedia
        (delta USDC = harga × qty ± fee), jadi PnL RT = (jual_eff − beli_eff)×qty
        EKSAK tanpa kurangi fee lagi.

        Args:
            real_qty: qty coin riil dari balance().
            mid: harga tengah orderbook (fallback bila d_usdc tak teratribusi).
            d_usdc_signed: delta USDC ber-tanda (<0 = USDC turun = beli;
                >0 = USDC naik = jual). None bila >1 pair bergerak (atribusi ambigu
                → pakai mid sebagai aproksimasi).

        Returns: dict ringkasan event utk logging, atau None bila debu/nol.
        """
        d_coin = real_qty - self.inv_qty
        if abs(d_coin) * mid < self.RECONCILE_DUST_USD:
            self.inv_qty = real_qty  # debu — sinkron senyap, tanpa event
            return None

        if self.inv_qty == 0 and d_coin > 0:
            self._set_inv_started(time.time())

        ev: dict = {"pair": self.pair, "d_coin": d_coin, "rts": 0, "rt_pnl": D(0)}

        if d_coin > 0:
            # NET BELI sejak rekonsiliasi terakhir
            if d_usdc_signed is not None and d_usdc_signed < 0:
                eff_px = (-d_usdc_signed) / d_coin   # USDC keluar / coin masuk (incl fee)
            else:
                eff_px = mid
            self.buy_q.append((eff_px, d_coin))
            fee_est = d_coin * eff_px * self.cfg.spot_maker_fee  # ponytail: estimasi fee dari base rate
            self.led.fill("E1", "S", self.pair, "buy", eff_px, d_coin, fee_est, True, None)
            ev.update(side="buy", price=eff_px, qty=d_coin)
        else:
            # NET JUAL
            sell_qty = -d_coin
            if d_usdc_signed is not None and d_usdc_signed > 0:
                eff_px = d_usdc_signed / sell_qty     # USDC masuk / coin keluar (net fee)
            else:
                eff_px = mid
            remain = sell_qty
            total_pnl = D(0)
            last_rt: str | None = None
            while remain > 0 and self.buy_q:
                bpx, bq = self.buy_q[0]
                take = min(bq, remain)
                self._rt += 1
                rt_id = f"E1-{self._rt}"
                vol = (bpx + eff_px) * take
                pnl = (eff_px - bpx) * take   # harga efektif sudah net fee
                self.led.rt_close(rt_id, "E1", self.pair, vol, pnl)
                last_rt = rt_id
                total_pnl += pnl
                ev["rts"] += 1
                if take == bq:
                    self.buy_q.pop(0)
                else:
                    self.buy_q[0] = (bpx, bq - take)
                remain -= take
            # jual melebihi buy_q (mis. inventori warisan tanpa basis) — rekam fill saja
            fee_est = sell_qty * eff_px * self.cfg.spot_maker_fee  # ponytail: estimasi fee dari base rate
            # Ikat fill ke RT hanya bila TAK ambigu: tepat 1 RT tertutup DAN qty jual
            # habis terpakai. Fill agregat yang menutup banyak RT / menyisakan sisa
            # tidak punya pasangan tunggal → biarkan None (jangan menebak).
            link_rt = last_rt if (ev["rts"] == 1 and remain == 0) else None
            self.led.fill("E1", "S", self.pair, "sell", eff_px, sell_qty, fee_est, True, link_rt)
            ev.update(side="sell", price=eff_px, qty=sell_qty, rt_pnl=total_pnl)

        self.inv_qty = real_qty
        if self.inv_qty == 0:
            self._set_inv_started(None)
        return ev

    def seed_baseline(self, real_qty: Decimal, mid: Decimal):
        """Inisialisasi inventori awal TANPA mencatat fill (startup).
        buy_q di-seed pada mid sehingga penjualan inventori warisan menghasilkan
        PnL ~0 (kita tak tahu cost basis sebenarnya — jujur, bukan mengarang profit)."""
        self.inv_qty = real_qty
        self.buy_q.clear()
        if real_qty > 0:
            self.buy_q.append((mid, real_qty))
            # B37/B45: pakai timestamp DB pair ini jika ada (lebih tua dari now
            # → inventori tidak baru).
            # Ini memastikan B36 age dihitung dari saat inventori PERTAMA KALI masuk,
            # bukan dari saat daemon di-restart (yang akan menipu age menjadi 0).
            if not self._restore_inv_started():
                self._set_inv_started(time.time())
        else:
            self._set_inv_started(None)

    # ── flush rule (perbaikan #3): inventori > X menit → jual ke bid ──
    def _check_flush(self, bk: Book):
        # Auto-reset flushing flag bila inventori sudah 0 (fill terdeteksi oleh reconcile)
        if self.inv_qty == 0:
            self._flushing = False
            return
        age = self._inv_age_minutes()
        if age < self.cfg.e1_inv_flush_minutes:
            return

        inv_usd = self._inv_usd(bk.mid)
        age_h = age / 60.0

        # B54: flush BLOKIR-kuoting hanya saat inventori MELEBIHI cap (over-exposure
        # nyata). Inventori tua tapi DALAM cap dibiarkan terkuras lewat quoting normal
        # ber-skew (yang TETAP menghasilkan volume SoPoints), bukan flush yang
        # menghentikan semua volume. Tanpa B54: inventori warisan 1751 menit tapi
        # cuma $69/$100 cap → flush abadi → 0 volume berjam-jam.
        # Pengecualian: bila B14 sudah pause (edge negatif), quoting normal mati →
        # flush tetap perlu agar modal tidak mati total (jalur last-resort B36).
        cap_usd = self.cfg.e1_inv_cap_per_pair
        within_cap = cap_usd > 0 and inv_usd <= cap_usd
        if within_cap and not self._quoting_paused:
            if self._flushing:
                self._flushing = False  # lepaskan blokir → quoting skew ambil alih
                logging.info("B54 flush skip (within cap): %s inv=$%.2f cap=$%.2f age=%.0fm "
                             "→ kuras via skew-quote (volume jalan)",
                             self.pair, float(inv_usd), float(cap_usd), age)
            return

        # B36: normal flush butuh inv_usd ≥ $10 (buffer atas minimum SoDEX $5).
        # Last-resort: bila E1 PAUSED dan inventori stuck >4 jam, turunkan threshold ke
        # $3 (coba flush walau kecil — lebih baik reject SoDEX daripada modal mati selamanya).
        min_notional = D("10")
        if self._quoting_paused and age_h > 4.0:
            min_notional = D("3")   # B36 last-resort threshold
            logging.info("B36 last-resort flush check: inv=$%.2f age=%.1fh paused=%s",
                         float(inv_usd), age_h, self._quoting_paused)

        if inv_usd < min_notional:
            # B42: inventori terlalu kecil untuk di-flush → reset _flushing agar quoting
            # tidak terblokir permanen. Terjadi saat flush order TTL-cancel tapi inv_qty
            # masih > 0 (order tidak terisi) dengan nilai di bawah notional minimum.
            if self._flushing:
                self._flushing = False
                logging.info("B42 _flushing reset %s: inv_usd=%.4f < min_notional=%.0f",
                             self.pair, float(inv_usd), float(min_notional))
            return

        # B40: cooldown 5 menit antara flush attempts.
        # Cegah _force_flush_now dipanggil setiap step() bila flush gagal/partial —
        # tanpa ini PEPE-flush memblokir SHIB/E1b selama 120 detik berulang-ulang.
        _now = time.time()
        if _now - self._last_flush_ts < 300:
            return
        self._last_flush_ts = _now

        self.tg.send(f"🛟 FLUSH: inventori {self.inv_qty:,.0f} qty ({inv_usd:.2f} USD) "
                     f"umur {age:.0f} menit — jual ke ask (B51)")
        self._force_flush_now(bk)
    
    # ── REGIME-ADAPTIVE HEDGE (2026-06-22) — solusi PR-terbesar user ──
    def _current_regime(self, bk: Book) -> str:
        """Regime gabungan: Intelligence+Pre-Sentiment (leading) + trend (fallback).
        Throttle ~60s (baca cache daemon + hitung)."""
        now = time.time()
        self._regime.update(float(bk.mid), now)
        if now - self._regime_cache_ts > 60:
            try:
                intel = intel_regime(read_intel_signal())
            except Exception:
                intel = None
            self._regime_label = combined_regime(self._regime.regime(), intel)
            self._regime_cache_ts = now
        return self._regime_label

    def _rebalance_hedge(self, bk: Book):
        """Hedge adaptif-regime: BEAR→short perp seukuran inventory (delta-neutral,
        lindungi); BULL→tutup hedge (nikmati upside); NEUTRAL→hedge separuh.
        Per-pair perp + konversi contract-size.

        OPEN/CLOSE FIX (2026-06-22): market-IOC gagal (oid=0) pada kedua arah:
        1) OPEN (sell): Set leverage isolated 5x sebelum pertama kali + fallback
           limit-IOC di bid jika market-IOC oid=0 (taker → fill terjamin).
        2) CLOSE (buy reduce_only): Fallback limit-IOC di ask + reset hedge_qty=0
           jika keduanya gagal (posisi sudah tidak ada di exchange → stop retry)."""
        if not self.cfg.e1_hedge_enabled:
            return
        # Staged rollout: hanya hedge pair yang dikonfigurasi (kosong = semua)
        if self.cfg.e1_hedge_pairs:
            allowed = [p.strip() for p in self.cfg.e1_hedge_pairs.split(",") if p.strip()]
            if self.pair not in allowed:
                return
        hedge_perp, mult = HEDGE_MAP.get(self.pair, (None, 1))
        if hedge_perp is None:
            return
        regime = self._current_regime(bk)
        ratio = {"BEAR": D("1.0"), "NEUTRAL": D("0.5"), "BULL": D("0.0")}.get(regime, D("0"))
        # Target short (kontrak) = inventory long × ratio / coins-per-contract
        target = hedge_qty_for_inventory(self.inv_qty * ratio, mult) if self.inv_qty > 0 else D(0)
        delta = target - self.hedge_qty   # >0 = tambah short; <0 = kurangi short
        try:
            perp_bk = self.x.book(hedge_perp)
            perp_mid = perp_bk.mid
        except Exception:
            return
        if perp_mid <= 0 or abs(delta) * perp_mid < self.cfg.e1_hedge_band:
            return  # dalam band → skip (cegah over-trading/whipsaw)
        side = "sell" if delta > 0 else "buy"     # sell=tambah short hedge; buy=kurangi
        reduce_only = (side == "buy")

        # ── Set leverage sebelum SHORT-OPEN (satu kali per perp, pola E2Dir) ──
        if side == "sell" and hedge_perp not in self._hedge_lev_set:
            _bin = getattr(self.x, "_sodex_bin", None) or "bin/sodex"
            _env = getattr(self.x, "_env", None) or dict(os.environ)
            try:
                r = subprocess.run(
                    [_bin, "leverage", hedge_perp, "5", "--mode", "isolated"],
                    capture_output=True, text=True, timeout=10, env=_env)
                out = (r.stdout + r.stderr).lower()
                if "leverage" in out:   # "leverage updated" OR "open position" → OK
                    self._hedge_lev_set.add(hedge_perp)
                    logging.info("HEDGE leverage 5x isolated: %s", hedge_perp)
                else:
                    logging.warning("HEDGE leverage set mungkin gagal %s: %s",
                                   hedge_perp, (r.stdout + r.stderr)[:120])
            except Exception as e:
                logging.warning("HEDGE leverage set exc %s: %s", hedge_perp, e)

        try:
            o = self.x.place_market_ioc(hedge_perp, side, abs(delta), perp_mid,
                                        reduce_only=reduce_only)
        except Exception as e:
            logging.warning("hedge place gagal %s: %s", hedge_perp, e)
            return

        # ── Fallback limit-IOC untuk OPEN (sell) dan CLOSE (buy) ──
        if (not o or not o.oid or o.oid == "0") and side == "sell":
            logging.info("HEDGE market-IOC oid=0 %s → fallback limit-IOC di bid", hedge_perp)
            try:
                bid_px = perp_bk.bid
                o = self.x.place_limit_ioc_perp(hedge_perp, "sell", abs(delta), bid_px)
                if o and o.oid and o.oid != "0":
                    logging.info("HEDGE limit-IOC SELL fallback OK %s oid=%s", hedge_perp, o.oid)
            except Exception as e:
                logging.warning("HEDGE limit-IOC SELL fallback exc %s: %s", hedge_perp, e)
                o = None

        if (not o or not o.oid or o.oid == "0") and side == "buy":
            # ponytail: reduce_only dipertahankan — jangan buka LONG jika posisi sudah nol
            logging.info("HEDGE market-IOC BUY oid=0 %s → fallback limit-IOC di ask", hedge_perp)
            try:
                ask_px = perp_bk.ask
                o = self.x.place_limit_ioc_perp(hedge_perp, "buy", abs(delta), ask_px)
                if o and o.oid and o.oid != "0":
                    logging.info("HEDGE limit-IOC BUY fallback OK %s oid=%s", hedge_perp, o.oid)
            except Exception as e:
                logging.warning("HEDGE limit-IOC BUY fallback exc %s: %s", hedge_perp, e)
                o = None
            if not o or not o.oid or o.oid == "0":
                # Kedua cara gagal → posisi sudah nol di exchange; reset akuntansi
                logging.warning("HEDGE BUY keduanya gagal %s — reset hedge_qty %.0f→0 "
                                "(posisi exchange sudah nol)", hedge_perp, float(self.hedge_qty))
                self._hedge_lev_set.discard(hedge_perp)   # set ulang leverage di open berikutnya
                self.hedge_qty = D(0)
                self.led.set_state(self._hedge_qty_key, "0")
                return

        if o and o.oid and o.oid != "0":
            filled = o.filled if o.filled > 0 else abs(delta)
            self.hedge_qty += filled if side == "sell" else -filled
            if self.hedge_qty < 0:
                self.hedge_qty = D(0)
            self.led.set_state(self._hedge_qty_key, str(self.hedge_qty))
            fee = perp_mid * filled * self.cfg.perp_maker_fee
            self.led.fill("E1", "P", hedge_perp, side, perp_mid, filled, fee, False, None)
            logging.info("HEDGE %s regime=%s ratio=%s %s %.0f %s (hedge_qty=%.0f inv=%.0f)",
                         self.pair, regime, ratio, side, float(filled), hedge_perp,
                         float(self.hedge_qty), float(self.inv_qty))
            if time.time() - self._last_hedge_tg > 300:
                self.tg.send(f"🛡️ HEDGE {self.pair} regime={regime}: {side} "
                             f"{float(filled):,.0f} {hedge_perp} (ratio {ratio})")
                self._last_hedge_tg = time.time()
        else:
            logging.warning("HEDGE %s gagal (oid=0) — lev_set=%s margin perps?",
                           hedge_perp, self._hedge_lev_set)
    
    # ── G2 gate ──
    def _gate_g2(self):
        rate = self.led.e1_recent_net_rate(200)
        if rate is None:
            return
        if rate >= self.cfg.e1_min_net_rt and self.ladder_i < len(self.cfg.e1_size_ladder) - 1:
            self.ladder_i += 1
            self.tg.send(f"✅ G2: net/RT {rate:.4%} — ramp size ke ${self.cfg.e1_size_ladder[self.ladder_i]}")
        elif rate < self.cfg.e1_min_net_rt and self.ladder_i > 0:
            self.ladder_i -= 1
            self.tg.send(f"⚠️ G2: net/RT {rate:.4%} < target — turun ke ${self.cfg.e1_size_ladder[self.ladder_i]}")

    def _check_profitability_gate(self):
        """B14: pause/resume quoting berdasar net rate JUJUR per-pair (akunting B13).
        Pause bila rate < pause_floor (n≥min); resume bila rate > resume_floor.
        Histeresis cegah flapping. Saat pause, E1 tetap kelola/flush inventori
        (tidak pasang quote baru) → hentikan bleed pada EV negatif (doktrin proyek)."""
        # B17: gate WAJIB pakai data JUJUR (post-B13) — phantom pra-B13 menipu gate.
        b13_ts = self.led.get_state("b13_activated_ts")
        since_iso = (datetime.fromtimestamp(float(b13_ts), UTC).isoformat()
                     if b13_ts and float(b13_ts) > 0 else None)
        rate, n = self.led.e1_recent_net_rate_pair(
            self.pair, n=100, min_n=self.cfg.e1_gate_min_n, since_iso=since_iso)
        if rate is None:
            return  # sampel < min → fail-open (kumpulkan data dulu)
        if not self._quoting_paused and rate < self.cfg.e1_pause_floor:
            self._quoting_paused = True
            self.led.set_state(self._b14_pause_key(), time.time())   # B28/B43: catat kapan mulai pause
            self.tg.send(f"⛔ B14 PAUSE quoting {self.pair}: net/RT {rate:.4%} < "
                         f"{float(self.cfg.e1_pause_floor):.4%} (n={n}) — EV negatif, stop bleed")
            logging.warning("B14 PAUSE %s: net_rate=%.5f n=%d", self.pair, float(rate), n)
        elif self._quoting_paused and rate > self.cfg.e1_resume_floor:
            self._quoting_paused = False
            self.led.set_state(self._b14_pause_key(), "0")   # B28/B43: bersihkan — gate kembali aktif
            self.tg.send(f"✅ B14 RESUME quoting {self.pair}: net/RT {rate:.4%} > "
                         f"{float(self.cfg.e1_resume_floor):.4%} (n={n}) — edge pulih")
            logging.info("B14 RESUME %s: net_rate=%.5f n=%d", self.pair, float(rate), n)
        elif self._quoting_paused and time.time() - self._last_gate_log > 300:
            logging.info("B14 %s masih PAUSE: net/RT %.5f (n=%d)", self.pair, float(rate), n)
            self._last_gate_log = time.time()
        # B30: log bila dalam trial period
        trial_until = float(self.led.get_state("b14_trial_until_ts"))
        if trial_until > time.time() and self._quoting_paused:
            if time.time() - self._last_gate_log > 60:
                remaining_h = (trial_until - time.time()) / 3600
                logging.info("B30 TRIAL %s: E1 aktif via trial (%.1fh tersisa) — rate=%.5f n=%d",
                             self.pair, remaining_h, float(rate) if rate else 0, n)
                self._last_gate_log = time.time()

    def _research_should_quote(self, spread: Decimal) -> bool:
        """B19: gate eksperimen ber-budget. Override pause B14 untuk quote HANYA
        saat spread ≥ research_min_spread, dengan cap keras: auto-HALT bila rugi
        jujur ≥ budget ATAU n RT ≥ target. Return True bila boleh quote (riset)."""
        st_ts = self.led.get_state("e1_research_start_ts")
        if not st_ts or float(st_ts) <= 0:
            return False  # belum diinisialisasi (defensif)
        since_iso = datetime.fromtimestamp(float(st_ts), UTC).isoformat()
        rts = self.led.e1_rts_since(since_iso)   # global (semua pair E1)
        n = len(rts)
        pnl_sum = sum(p for p, _ in rts)
        budget_spent = -pnl_sum if pnl_sum < 0 else D(0)
        if budget_spent >= self.cfg.e1_research_budget:
            if time.time() - self._last_gate_log > 300:
                self.tg.send(f"⛔ B19 EKSPERIMEN HALT: budget ${float(budget_spent):.2f} "
                             f"≥ ${float(self.cfg.e1_research_budget):.2f} — stop, modal terlindungi")
                logging.warning("B19 HALT budget: spent=%.4f n=%d", float(budget_spent), n)
                self._last_gate_log = time.time()
            return False
        if n >= self.cfg.e1_research_target_n:
            if time.time() - self._last_gate_log > 300:
                self.tg.send(f"✅ B19 EKSPERIMEN COMPLETE: n={n} ≥ {self.cfg.e1_research_target_n} "
                             f"— jalankan 'e1experiment' utk verdict")
                logging.info("B19 COMPLETE: n=%d", n)
                self._last_gate_log = time.time()
            return False
        return spread >= self.cfg.e1_research_min_spread

    # ── iterasi utama ──
    def step(self):
        bk = self.x.book(self.pair)
        
        # Perbaikan #3: cek flush rule SETIAP iterasi
        self._check_flush(bk)
        
        # ── BATCH: ambil SEMUA order dalam 1 API call ──
        is_perp = "-USD" in self.pair.upper()
        market = "perps" if is_perp else "spot"
        # Gunakan _sodex_list agar SEMUA order dikembalikan (bukan hanya data[0])
        all_orders = self.x._sodex_list(["orders", "list", market, "--format", "json"], timeout=15)
        # Build lookup: orderID → data
        order_map = {str(o.get("orderID", "")): o for o in all_orders}
        
        # re-quote: buang order kedaluwarsa (pakai cache)
        # S1 fix (audit 06-Okt-2026): tag scope market bareng cache -- self.x
        # DIBAGI oleh E1/E2Perps(x3)/E2Directional, jadi poll_fill() HARUS tahu
        # cache ini dari market APA sebelum mempercayainya (cegah E2/E2Dir baca
        # "filled=0" palsu dari cache spot/market lain yg kebetulan masih nempel).
        self.x._poll_cache = order_map
        self.x._poll_cache_market = market
        keep = []
        missed = 0  # counter phantom fills
        for o in self.orders:
            # B13: di reconcile_mode (live), fill di-catat oleh _reconcile_all_from_balance
            # dari saldo riil. poll_fill di sini HANYA utk lifecycle order (keep/cancel),
            # TIDAK mencatat fill (cegah double-count dengan reconciler).
            if not self.reconcile_mode:
                inc = self.x.poll_fill(o)
                if inc > 0:
                    self._on_fill(o, inc)
                # ── CROSS-CHECK: order hilang + partial fill + umur cukup → fully filled ──
                if str(o.oid) not in order_map and o.filled > 0 and (time.time() - o.ts) > 5:
                    remaining = o.qty - o.filled
                    if remaining > 0:
                        self._on_fill(o, remaining)
                        missed += remaining
                        logging.warning("PHANTOM FILL: order %s (filled=%.0f/%.0f, age=%.0fs) hilang — recover sisa %.0f",
                                       o.oid, o.filled, o.qty, time.time()-o.ts, remaining)
                    continue
                # B41: order hilang dari exchange tapi filled=0 (order tidak pernah terisi,
                # mungkin TTL-cancel atau reject di sisi exchange). Drop silently — jangan
                # spam poll_fill setiap iterasi. reconcile_mode handles inventori via balance.
                elif str(o.oid) not in order_map and o.filled == 0 and (time.time() - o.ts) > 5:
                    continue
            else:
                # reconcile_mode: cukup tahu apakah order masih terbuka di exchange
                if str(o.oid) not in order_map:
                    continue  # hilang (terisi/dibatalkan) → stop track; reconciler urus inventori
            ttl = RNG.uniform(*self.cfg.e1_quote_ttl_s)
            if o.filled >= o.qty:
                continue
            if time.time() - o.ts > ttl:
                self.x.cancel(o)
            else:
                keep.append(o)
        self.x._poll_cache = None  # clear cache
        self.orders = keep
        if missed > 0:
            logging.info("CROSS-CHECK: %s phantom fills recovered this iteration", missed)
        
        # B14: gate profitabilitas — pause quoting bila edge jujur negatif
        self._check_profitability_gate()
        # B30: trial period — override B14 pause sementara untuk kumpul RT baru
        trial_until = float(self.led.get_state("b14_trial_until_ts"))
        in_b30_trial = (trial_until > time.time() and self._quoting_paused)
        # B19: mode eksperimen (bila aktif) override pause — quote hanya spread lebar,
        # ber-budget. Jika tidak, jalur normal (pause + min_spread).
        # B40: auto-reset _flushing bila inventori sudah 0 (order terisi penuh)
        if self.inv_qty == 0:
            self._flushing = False
        if self.cfg.e1_research_enabled:
            allow_quote = self._research_should_quote(bk.spread)
        elif in_b30_trial:
            # B30: quote saat trial meski paused — rate evaluation tetap berjalan
            allow_quote = (bk.spread >= self._min_spread()) and not self._flushing
        else:
            # B40: _flushing=True blokir buy baru hingga flush order terisi (inv=0)
            allow_quote = (not self._quoting_paused and not self._flushing
                           and bk.spread >= self._min_spread())
        if allow_quote and len(self.orders) < 4:
            before_orders = len(self.orders)
            placed = self._place_two_sided(bk, aggressive=0)  # pure maker — spread capture, fill terekam
            if placed == 0 and len(self.orders) == before_orders and time.time() - self._last_quote_diag_log > 60:
                logging.info(
                    "B44 quote no-op %s: spread=%.5f min=%.5f paused=%s flushing=%s inv=%.0f cap=%.2f reason=%s",
                    self.pair, float(bk.spread), float(self._min_spread()),
                    self._quoting_paused, self._flushing, self.inv_qty,
                    float(self.cfg.e1_inv_cap_per_pair), self._last_place_skip_reason)
                self._last_quote_diag_log = time.time()
        elif not allow_quote and time.time() - self._last_quote_diag_log > 60:
            logging.info(
                "B44 quote blocked %s: spread=%.5f min=%.5f paused=%s flushing=%s research=%s trial=%s orders=%d",
                self.pair, float(bk.spread), float(self._min_spread()),
                self._quoting_paused, self._flushing,
                self.cfg.e1_research_enabled, in_b30_trial, len(self.orders))
            self._last_quote_diag_log = time.time()
        
        self._rebalance_hedge(bk)
        
        if self._rt and self._rt % 50 == 0:
            self._gate_g2()
        if self._rt % 25 == 0:
            # Sertakan PAIR: dua engine (PEPE & SHIB) sebelumnya log "E1 inv=…"
            # identik → tampak seperti thrashing 0↔N padahal hanya bergantian.
            logging.info("💓 micro-hb %s RT=%d | inv=%.0f qty | orders=%d",
                         self.pair, self._rt, self.inv_qty, len(self.orders))
    
    # ── shutdown: WAJIB flat (perbaikan #4) ──
    def shutdown(self):
        """Fast shutdown — EOD flush only. JANGAN cancel loop (API unreliable)."""
        if self.inv_qty != 0 and self.cfg.e1_force_flat_eod:
            try:
                bk = self.x.book(self.pair)
                inv_usd = self._inv_usd(bk.mid)
                if inv_usd >= D("10"):
                    self.tg.send(f"🌅 EOD FLAT: menutup inventori {self.inv_qty:,.0f} qty (${inv_usd:.2f})")
                    self._force_flush_now(bk)
            except Exception as e:
                logging.warning("EOD flush gagal: %s — inventory akan menginap", e)
                self.tg.send(f"⚠️ EOD FLAT GAGAL: inventory {self.inv_qty:,.0f} qty menginap")
        # JANGAN cancel order — next daemon instance akan handle via step() loop
    
    def _force_flush_now(self, bk: Book):
        """B40: Non-blocking flush — tempatkan sell order, kembalikan SEGERA.

        Sebelumnya (B39): loop poll 120 detik memblokir seluruh run-loop → SHIB/E1b
        tidak bisa step, 1 warning/0.5s. Sekarang: place+return, step() normal
        mengelola order via reconcile_mode. _reconcile_all_from_balance update inv_qty
        saat fill terdeteksi dari delta saldo.

        B39 balance-sync tetap ada di sini sebagai early-exit: jika exchange sudah
        menunjukkan 0 (flush sebelumnya sudah terisi), segera bersihkan state tanpa
        menempatkan order baru yang tidak perlu.
        """
        # B39: sync segera dari exchange — cek apakah inventory sudah 0 sebelum place
        try:
            bal = self.x.balance()
            coin = "v" + self.pair.split("/")[0]
            real_qty = bal.get(coin, D(0))
            if real_qty < self.inv_qty:
                logging.info("B39/B40 pre-flush sync: %s ledger=%s exchange=%s → koreksi",
                             self.pair, float(self.inv_qty), float(real_qty))
                self.inv_qty = real_qty
                self.buy_q.clear()
                # B46: dust < 1 unit (mis. 0.917835 PEPE) → tidak bisa dijual → clear
                if self.inv_qty < D("1"):
                    self.inv_qty = D("0")
                if self.inv_qty == 0:
                    self._inv_started = None
                    self._flushing = False
                    self.tg.send("✅ FLUSH selesai (balance-sync) — inventori netral")
                    return
        except Exception as e:
            logging.warning("B40 pre-flush balance-sync gagal: %s", e)

        if self.inv_qty == 0:
            self._inv_started = None
            self._flushing = False
            return

        # Place sell order — tidak block, step() yang track lifecycle
        # B51: flush pakai bk.ask bukan bk.bid — place_post_only tidak bisa crossing;
        # sell at bid = selalu ditolak karena ada buyer di bid (oid=0 loop forever).
        # Sell at ask = resting maker; terisi saat buyer hit ask. Lebih lambat tapi works.
        side = "sell" if self.inv_qty > 0 else "buy"
        # B60 (29-Sep-2026): JANGAN pasang tepat di touch. Temuan Juni-2026 yang HILANG saat
        # refactor: SoDEX spot MENOLAK GTC-limit SELL tepat di best ask → oid=0 senyap
        # (inventori nyangkut 631 menit). Sell di ask+offset rest sebagai maker valid.
        _exp = bk.bid.as_tuple().exponent
        _tick = D(1).scaleb(_exp) if isinstance(_exp, int) else D("0.00000001")
        _off = max((bk.ask - bk.bid) * D("0.05"), _tick)   # minimal 1 TICK nyata
        px = (bk.ask + _off) if side == "sell" else (bk.bid - _off)
        if px <= 0:
            px = bk.ask if side == "sell" else bk.bid
        qty = abs(self.inv_qty)

        o = self.x.place_post_only(self.pair, side, px, qty)
        if o.oid != "0":
            self._flushing = True
            self.orders.append(o)
            logging.info("B40 flush placed: %s %s qty=%.0f px=%s oid=%s",
                         self.pair, side, float(qty), float(px), o.oid)
            self.tg.send(f"📤 FLUSH order ditempatkan: {qty:,.0f} qty @ {float(px):.8f}")
        else:
            # B60 (29-Sep-2026): post-only ditolak (harga stale/menembus buku) → JANGAN biarkan
            # inventori menumpuk. Kasus nyata: 1.108.000 vSHIB macet 631 menit gagal flush,
            # sementara leg BUY terus terisi = akumulasi satu sisi (rugi struktural).
            # Eskalasi ke market-IOC: fill terjamin (taker); biaya taker ≪ risiko inventori menginap.
            logging.warning("B60 flush post-only oid=0 → eskalasi market-IOC %s %s qty=%.0f",
                            self.pair, side, float(qty))
            _o2 = None
            try:
                _o2 = self.x.place_market_ioc(self.pair, side, qty,
                                              bk.bid if side == "sell" else bk.ask)
            except Exception as e:
                logging.warning("B60 flush market-IOC exception: %s", e)
            if _o2 is not None and _o2.oid and _o2.oid != "0":
                self._flushing = True
                self.orders.append(_o2)
                self.tg.send(f"🛟 FLUSH via market-IOC (post-only ditolak): {qty:,.0f} qty "
                             f"— inventori dinetralkan, fee taker diterima")
            else:
                logging.warning("B60 flush GAGAL dua jalur (post-only + market-IOC) %s", self.pair)
                self.tg.send(f"⚠️ FLUSH GAGAL dua jalur — inventori {qty:,.0f} qty masih terbuka; "
                             f"retry memakai backoff adaptif")

# ============================== 8. ENGINE-2 PERPS ============================

class Engine2Perps:
    """E2 v2 — Momentum-filtered maker churn (Jun 2026).
    
    v1 (random): 605 RTs, 3.1% WR, -$36.75 — NO EDGE (coin flip + fees).
    v2 (momentum): Only trades in direction of 5-min trend, with 0.5% stop-loss.
    Edge thesis: short-term momentum exists in crypto perps; maker fees are low
    enough that a 55%+ directional edge yields positive expectancy.
    """
    def __init__(self, cfg, adapter, led, guards, treasury, tg, pair: str | None = None):
        self.cfg, self.x, self.led, self.g, self.t, self.tg = cfg, adapter, led, guards, treasury, tg
        self.pair = pair or cfg.churn_perp  # override for multi-pair
        # Seed monotonik dari ledger — ID RT tidak boleh dipakai ulang lintas restart
        # (lihat catatan di E1; insiden 28-Sep-2026).
        self._rt = self.led.next_rt_seq("E2")
        self._last_px: Decimal | None = None
        self._last_px_ts: float = 0.0
        self._consecutive_failures = 0
        self._last_skip_log = 0.0

    def _state_key(self, suffix: str) -> str:
        clean = self.pair.replace("/", "_").replace("-", "_")
        return f"e2_{suffix}_{clean}"

    def _route_key(self, suffix: str) -> str:
        return f"e2_route_{suffix}"

    def _disabled_until(self) -> float:
        try:
            return float(self.led.get_state(self._state_key("disabled_until"), "0"))
        except Exception:
            return 0.0

    def _route_disabled_until(self) -> float:
        try:
            return float(self.led.get_state(self._route_key("disabled_until"), "0"))
        except Exception:
            return 0.0

    def _cooldown_active(self) -> bool:
        route_until = self._route_disabled_until()
        if route_until > time.time():
            if time.time() - self._last_skip_log > 60:
                logging.error("E2 perps route cooldown active for %.0fs — all E2 churn skipped",
                              route_until - time.time())
                self._last_skip_log = time.time()
            return True
        until = self._disabled_until()
        if until <= time.time():
            return False
        if time.time() - self._last_skip_log > 60:
            logging.warning("E2 pair %s cooldown active for %.0fs — skip",
                            self.pair, until - time.time())
            self._last_skip_log = time.time()
        return True

    def _record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        logging.warning("E2 %s failure %d/%d: %s",
                        self.pair, self._consecutive_failures,
                        self.cfg.e2_pair_max_failures, reason[:160])
        if self._consecutive_failures >= self.cfg.e2_pair_max_failures:
            until = time.time() + self.cfg.e2_pair_cooldown_s
            self.led.set_state(self._state_key("disabled_until"), D(str(until)))
            self._consecutive_failures = 0
            logging.error("E2 pair %s disabled for %ds after repeated failures",
                          self.pair, self.cfg.e2_pair_cooldown_s)
        self._record_route_failure(reason)

    def _record_route_failure(self, reason: str) -> None:
        now = time.time()
        first = float(self.led.get_state(self._route_key("first_failure_ts"), "0"))
        count = int(self.led.get_state(self._route_key("failure_count"), "0"))
        if first <= 0 or now - first > self.cfg.e2_route_fail_window_s:
            first = now
            count = 0
        count += 1
        self.led.set_state(self._route_key("first_failure_ts"), D(str(first)))
        self.led.set_state(self._route_key("failure_count"), D(str(count)))
        if count >= self.cfg.e2_route_max_failures:
            until = now + self.cfg.e2_route_cooldown_s
            self.led.set_state(self._route_key("disabled_until"), D(str(until)))
            self.led.set_state(self._route_key("first_failure_ts"), D("0"))
            self.led.set_state(self._route_key("failure_count"), D("0"))
            logging.error(
                "E2 perps route disabled for %ds after %d failures in %ds; last=%s",
                self.cfg.e2_route_cooldown_s,
                count,
                self.cfg.e2_route_fail_window_s,
                reason[:160],
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self.led.set_state(self._state_key("disabled_until"), D("0"))
        self.led.set_state(self._route_key("first_failure_ts"), D("0"))
        self.led.set_state(self._route_key("failure_count"), D("0"))

    def _get_trend(self) -> str:
        """Detect short-term momentum: 'up', 'down', or 'flat'.
        SoDEX v2: uses 'tickers perps' CLI (REST API path changed post-upgrade)."""
        try:
            tickers = self.x._sodex_list(["tickers", "perps", "--format", "json"], timeout=10)
            cur = None
            for t in tickers:
                if t.get("symbol") == self.pair:
                    cur = D(str(t.get("markPrice", t.get("lastPx", "0"))))
                    break
            if cur is None or cur <= 0:
                return 'flat'
        except Exception:
            return 'flat'

        now = time.time()
        # On first call or if cache expired (>120s), just cache and return flat
        if self._last_px is None or now - self._last_px_ts > 120:
            self._last_px = cur
            self._last_px_ts = now
            return "flat"

        # Calculate 5-min return
        ret = float((cur - self._last_px) / self._last_px)

        # Update cache
        self._last_px = cur
        self._last_px_ts = now

        # Signal thresholds (calibrated for perps maker fees of ~0.022% round-trip)
        if ret > 0.0005:   # +0.05% in 5 min → upward momentum
            return "up"
        elif ret < -0.0005:  # -0.05% → downward momentum
            return "down"
        return "flat"

    def _maker_leg(self, side: str, usd: Decimal, stop_loss_pct: Decimal = D("0.005"), aggressive: int = 1) -> tuple[Decimal, Decimal] | None:
        """Place maker order with stop-loss monitoring.
        
        aggressive=0: pure maker at bid/ask (slow, lowest fee).
        aggressive=1: mid-price (moderate fill rate).
        aggressive=2: near-taker (bid+0.7spread for buy, ask-0.7spread for sell — fastest fills).
        """
        try:
            bk = self.x.book(self.pair)
        except Exception as e:
            self._record_failure(f"book_unavailable: {e}")
            return None
        spr = bk.ask - bk.bid
        if aggressive >= 2:
            # Near-taker: price very close to opposite side — fills fast, still maker
            entry_px = bk.bid + spr * D("0.7") if side == "buy" else bk.ask - spr * D("0.7")
        elif aggressive == 1:
            entry_px = bk.mid
        else:
            # B56: maker di touch SERING ditolak (oid=0) pada 1-tick perps — saat
            # harga geser 1 tick antar read↔place, order jadi marketable → SoDEX
            # tolak. Fix: geser INSIDE-FAVOR sebanyak e2_maker_tick_offset tick
            # (buy DI BAWAH bid, sell DI ATAS ask). Pada market 1-tick spr=1 tick,
            # offset=1 → order rest aman walau harga geser 1 tick. Trade-off: isi
            # lebih lambat tapi placement PASTI valid (uji manual XPL@bid-3tick rest).
            off = spr * D(str(self.cfg.e2_maker_tick_offset))
            entry_px = (bk.bid - off) if side == "buy" else (bk.ask + off)
            if entry_px <= 0:
                entry_px = bk.bid if side == "buy" else bk.ask
        qty = usd / entry_px
        try:
            o = self.x.place_post_only(self.pair, side, entry_px, qty)
        except Exception as e:
            self._record_failure(f"place_exception: {e}")
            return None
        if not o.oid or o.oid == "0":
            self._record_failure("order_rejected_oid0")
            return None  # order gagal dipasang

        deadline = time.time() + RNG.uniform(*self.cfg.e2_fill_timeout_s)
        got = D(0)
        # Stop-loss price
        # K1 fix (audit 06-Okt-2026): arah SL sebelumnya tertukar — buy(long)
        # harus stop saat harga TURUN, sell(short) harus stop saat harga NAIK.
        sl_px = entry_px * (D("1") - stop_loss_pct) if side == "buy" else entry_px * (D("1") + stop_loss_pct)

        while time.time() < deadline:
            inc = self.x.poll_fill(o)
            if inc > 0:
                got += inc
                fee = entry_px * inc * self.cfg.perp_maker_fee
                if not self.t.authorize(fee):
                    if not self.g.principal_fee_ok(fee):
                        self.x.cancel(o); return None
                    self.g.spend_principal_fee(fee)
                self.led.fill("E2", "P", self.pair, side, entry_px, inc, fee, True, None)
            if o.filled >= o.qty:
                return entry_px, got

            # Stop-loss check: poll current mark price
            try:
                cur_bk = self.x.book(self.pair)
                cur_mid = cur_bk.mid
                if (side == "buy" and cur_mid < sl_px) or (side == "sell" and cur_mid > sl_px):
                    logging.info("E2 STOP-LOSS: %s leg hit SL (entry=%.2f sl=%.2f mid=%.2f)",
                                 side, float(entry_px), float(sl_px), float(cur_mid))
                    self.x.cancel(o)
                    return (entry_px, got) if got > 0 else None
            except Exception:
                pass  # book fetch gagal → lanjut tanpa SL check

            time.sleep(0.5)

        self.x.cancel(o)
        return (entry_px, got) if got > 0 else None

    def churn_cycle(self):
        """v3: PURE MAKER churn — no momentum filter, aggressive=0.
        Profitable when spread > 2× maker fee (0.024%).
        Jun 17: switched from momentum (losing) to pure maker (profitable).

        Crash-recovery: position state is persisted only AFTER leg1 has a
        confirmed fill, then cleared AFTER leg2 closes. On daemon restart,
        Orchestrator calls _reconcile_e2_positions() for any unclosed row.
        """
        if self._cooldown_active():
            return False

        usd = D(str(RNG.uniform(float(self.cfg.e2_clip_usd[0]), float(self.cfg.e2_clip_usd[1]))))
        est_fee = usd * 2 * self.cfg.e2_est_cost_rate
        if not self.t.authorize(est_fee):
            return False

        # Random direction — pure MM doesn't need momentum edge
        first = "buy" if RNG.random() < 0.5 else "sell"
        logging.info("E2 churn: pair=%s dir=%s usd=$%.0f", self.pair, first, float(usd))

        # Leg 1: pure maker at best bid/ask — captures full spread
        leg1 = self._maker_leg(first, usd, stop_loss_pct=D("0.01"), aggressive=0)
        if not leg1:
            return True

        px1, q1 = leg1
        if q1 <= 0 or px1 <= 0:
            self._record_failure("leg1_returned_nonpositive_fill")
            return True

        # Crash-recovery begins only after a confirmed fill exists. Writing an
        # intent row before this point created local ghosts when book/place failed.
        pos_rowid = self.led.e2_save_open(self.pair, first, q1, px1)
        self._record_success()

        leg2_usd = px1 * q1
        if leg2_usd < self.cfg.e2_clip_usd[0] / D("10"):
            self.led.e2_clear_open(pos_rowid)
            return True

        # Leg 2: close opposite side, also pure maker
        second = "sell" if first == "buy" else "buy"
        leg2 = self._maker_leg(second, leg2_usd, aggressive=0)

        self._rt += 1
        # K2 fix (audit 06-Okt-2026): leg2 truthy hanya berarti got>0 (bisa PARTIAL
        # fill) — klirkan record hanya jika leg2 menutup qty leg1 SEPENUHNYA, agar
        # residu posisi di exchange tetap tercatat untuk reconcile saat partial.
        leg2_full = bool(leg2) and leg2[1] >= q1
        if leg2:
            px2, q2 = leg2
            vol = px1 * q1 + px2 * q2
            pnl = (px2 - px1) * min(q1, q2) * (D("1") if first == "buy" else D("-1")) \
                  - vol * self.cfg.perp_maker_fee
            self.led.rt_close(f"E2-{self._rt}", "E2", self.pair, vol, pnl)

        # Position closed (or failed-to-close → left open on exchange, but at least
        # the record exists; reconcile will handle it on next startup).
        # Only clear if leg2 fully closed leg1's qty — partial fill still leaves
        # residual exposure on exchange and MUST stay tracked for reconcile.
        if leg2_full:
            self.led.e2_clear_open(pos_rowid)
            self._record_success()
        else:
            reason = "leg2_close_failed" if not leg2 else f"leg2_partial_fill q2={leg2[1]}/q1={q1}"
            self._record_failure(reason)
            logging.warning("E2 leg2 %s: position record %d kept for reconcile on next startup", reason, pos_rowid)
        return True

    def candc_opportunity(self) -> bool:
        """Slot M2/M6: layak bila funding 1-interval > fee siklus 2-kaki perps."""
        try:
            f = self.x.funding_rate(self.pair)
        except Exception:
            return False
        cycle_fee_rate = 2 * self.cfg.perp_maker_fee
        return f > cycle_fee_rate

# ==================== 8b. ENGINE-2 DIREKSIONAL (PHASE 2) ====================

def _scan_best_funding_pair(adapter: "ExchangeAdapter") -> tuple[str | None, "Decimal"]:
    """B23: Scan semua pair perps SoDEX, kembalikan pair dengan |funding| tertinggi.

    SoDEX funding rate skala ~0.001-0.008%/8h (jauh lebih kecil dari Binance 0.01-0.1%).
    Hardcode satu pair (ENA-USD) tidak efektif karena funding flat.
    Scan dinamis memastikan kita selalu melihat pair paling 'panas'.

    Returns: (pair_name, funding_rate) atau (None, 0) jika semua pair gagal.
    """
    try:
        tickers = adapter._sodex_list(["tickers", "perps", "--format", "json"], timeout=12)
        best_pair, best_fr = None, D(0)
        for t in tickers:
            fr = D(str(t.get("fundingRate", 0)))
            if abs(fr) > abs(best_fr):
                best_fr = fr
                best_pair = t.get("symbol")
        return best_pair, best_fr
    except Exception:
        return None, D(0)


def generate_directional_signal(adapter: "ExchangeAdapter", pair: str | None,
                                 cfg: "Config") -> dict | None:
    """Hasilkan sinyal arah dari funding rate + OBI (order-book imbalance).

    LOGIKA (falsification-first):
    • Funding rate tinggi-positif (> threshold) → longs kelebihan → SHORT (squeeze).
    • Funding rate rendah-negatif (< -threshold) → shorts kelebihan → LONG (squeeze).
    • OBI = (bid_size - ask_size) / (bid_size + ask_size) harus SELARAS arah signal.
      OBI > 0 = beli dominan (bullish), OBI < 0 = jual dominan (bearish).
      Misalnya signal SHORT valid jika OBI < -obi_thr (konfirmasi tekanan jual).
    • Tanpa konfirmasi OBI → grade turun. Tanpa sinyal → return None.

    B23: Bila pair=None, scan semua pair SoDEX dan pilih yang paling ekstrem.
    Threshold dikalibrasi untuk skala SoDEX (lihat TE_E2_DIR_FUNDING_THR).
    Lihat catatan kalibrasi di Config: SoDEX max funding ~0.008%/8h (10× lebih kecil
    dari Binance), jadi threshold default 0.05% TIDAK PERNAH tercapai. Default baru:
    0.003%/8h (TE_E2_DIR_FUNDING_THR=0.00003).

    Grade:
      S (≥2×threshold funding, konfirmasi OBI kuat) → eksekusi prioritas
      A (≥1.5×threshold, OBI selaras)
      B (≥threshold, OBI lemah/netral)
      di bawah threshold → None (tidak ada sinyal)

    Returns dict: {side, grade, score, funding_rate, obi, pair} atau None.
    """
    # B23: scan dinamis bila pair tidak dispesifikasikan
    if pair is None:
        pair, fr = _scan_best_funding_pair(adapter)
        if pair is None:
            return None  # gagal ambil tickers
    else:
        try:
            fr = adapter.funding_rate(pair)
        except Exception:
            return None

    # S9 fix (audit 06-Okt-2026): book() HANYA punya bid/ask PRICE (bukan depth
    # size), dan Book.mid = (bid+ask)/2 murni — SECARA ALJABAR b_dist == a_dist
    # SELALU (keduanya = (ask-bid)/2), jadi proxy lama (a_dist-b_dist)/(a_dist+b_dist)
    # SELALU 0 -- tak pernah bisa konfirmasi apa pun (dibuktikan manual, bukan
    # DUGAAN). OBI nyata butuh depth data (lihat scripts/sodex_prereg_f3.py:
    # OBI20 asli dari collector terpisah, dipakai F3 eval #44). Di sini: OBI
    # TIDAK TERSEDIA dari adapter ini -> grading funding-only (grade B saja),
    # jangan pura-pura S/A "OBI-confirmed" yang matematis mustahil terjadi.
    # Behavior TIDAK berubah: cabang S/A lama sudah unreachable (obi selalu 0).
    obi = None

    thr = cfg.e2_dir_funding_thr
    abs_fr = abs(fr)

    if abs_fr < thr:
        return None  # tidak ada sinyal (funding terlalu kecil)

    # Tentukan arah: funding positif besar → SHORT (longs akan bayar → squeeze)
    side = "sell" if fr > 0 else "buy"

    # Grading: hanya funding (OBI tak tersedia, lihat komentar di atas)
    grade = "B"
    score = D("70")

    return {
        "pair": pair, "side": side, "grade": grade, "score": score,
        "funding_rate": fr, "obi": obi,
    }


def _scan_liquid_perps(adapter: "ExchangeAdapter", min_vol24h: "Decimal",
                       top_n: int) -> list[str]:
    """Kembalikan pair perps paling likuid (vol24h ≥ min), urut desc, maks top_n.
    Sumber throughput sinyal momentum: banyak pair likuid = banyak peluang."""
    try:
        tickers = adapter._sodex_list(["tickers", "perps", "--format", "json"], timeout=12)
    except Exception:
        return []
    items = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sym = t.get("symbol", "")
        try:
            vol = D(str(t.get("quoteVolume", 0) or t.get("volume", 0) or 0))
        except Exception:
            vol = D(0)
        if sym and vol >= min_vol24h:
            items.append((sym, vol))
    items.sort(key=lambda x: -x[1])
    return [s for s, _ in items[:top_n]]


def generate_momentum_signal(adapter: "ExchangeAdapter", pair: str, cfg: "Config",
                             price_cache: dict) -> dict | None:
    """Sinyal momentum frekuensi-tinggi (KONTINUASI): gerak harga terkini → arah lanjut.

    HIPOTESIS (falsification-first): pada horizon pendek, perps kripto/ekuitas
    menunjukkan momentum (kelanjutan) — harga naik tajam cenderung lanjut naik.
    Diuji PAPER dulu; bila WR<50% → hipotesis gugur → balik ke reversi.

    price_cache: {pair: (last_mid, last_ts)} dipelihara lintas panggilan.
    OBI (proxy spread-distance) sebagai konfirmasi — searah → grade naik.

    Returns {pair, side, grade, score, momentum, obi} atau None.
    """
    try:
        bk = adapter.book(pair)
        cur = bk.mid
    except Exception:
        return None
    if cur <= 0:
        return None
    now = time.time()
    prev = price_cache.get(pair)
    if prev is None:
        price_cache[pair] = (cur, now)
        return None  # observasi pertama — belum ada referensi
    last_px, last_ts = prev
    dt = now - last_ts
    # FIX: JANGAN overwrite cache tiap panggilan — biarkan dt tumbuh hingga min_dt.
    # Bila reset tiap ~7s (interval scan), dt selalu <20s → momentum tak pernah terhitung.
    if dt < cfg.e2_mom_min_dt:
        return None  # tahan referensi, tunggu dt cukup
    # dt ≥ min_dt: konsumsi referensi, set titik acuan baru
    price_cache[pair] = (cur, now)
    if last_px <= 0 or dt > cfg.e2_mom_max_dt:
        return None  # stale (acuan sudah direset)
    ret = (cur - last_px) / last_px
    thr = cfg.e2_mom_thr
    if abs(ret) < thr:
        return None  # tidak ada gerak cukup
    # REVERSI (default, kontinuasi terfalsifikasi WR=37.5%): lonjakan naik → SELL
    #   (harga balik), turun → BUY. KONTINUASI: naik → buy. Pilih via e2_mom_reversion.
    if cfg.e2_mom_reversion:
        side = "sell" if ret > 0 else "buy"
    else:
        side = "buy" if ret > 0 else "sell"
    # S9 fix (audit 06-Okt-2026): proxy OBI sama dgn generate_directional_signal
    # -- SELALU 0 secara aljabar (Book.mid=(bid+ask)/2 -> b_dist==a_dist selalu),
    # `aligned` jadi SELALU False. Behavior TIDAK berubah (grade S sudah
    # unreachable sebelumnya karena butuh aligned=True; A-tier tetap jalan via
    # mag>=1.5 saja). OBI dihapus dari grading, bukan dipura-purakan.
    mag = abs(ret) / thr  # 1.0 = di threshold
    if mag >= 1.5:
        grade = "A"
    else:
        grade = "B"
    score = float(min(D(100), mag * D(40)))
    return {
        "pair": pair, "side": side, "grade": grade, "score": score,
        "momentum": float(ret), "obi": None, "funding_rate": D(0),
    }


def _fetch_perp_snapshots(adapter: "ExchangeAdapter") -> dict:
    """Snapshot L1 semua perps dari tickers (1 panggilan): {pair: (bidPx,bidSz,askPx,askSz)}.
    Efisien — sumber data OFI (order-flow imbalance) untuk semua pair sekaligus."""
    out = {}
    try:
        tickers = adapter._sodex_list(["tickers", "perps", "--format", "json"], timeout=12)
    except Exception:
        return out
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sym = t.get("symbol", "")
        try:
            bpx = float(t.get("bidPx", 0) or 0); bsz = float(t.get("bidSz", 0) or 0)
            apx = float(t.get("askPx", 0) or 0); asz = float(t.get("askSz", 0) or 0)
        except Exception:
            continue
        if sym and bpx > 0 and apx > 0:
            out[sym] = (bpx, bsz, apx, asz)
    return out


def _ofi(prev: tuple, now: tuple) -> float:
    """Order-Flow Imbalance (Cont-Kukanov-Stoikov 2014) dari 2 snapshot L1.
    prev/now = (bidPx, bidSz, askPx, askSz). OFI>0 = tekanan beli (prediksi naik).

    Bid: harga naik → +qty baru; sama → Δqty; turun → −qty lama (demand ditarik).
    Ask: harga naik → −qty lama (supply ditarik); sama → Δqty; turun → +qty (supply masuk).
    OFI = kontribusi_bid − kontribusi_ask.
    """
    pb0, qb0, pa0, qa0 = prev
    pb1, qb1, pa1, qa1 = now
    if pb1 > pb0:   eb = qb1
    elif pb1 == pb0: eb = qb1 - qb0
    else:           eb = -qb0
    if pa1 > pa0:   ea = -qa0
    elif pa1 == pa0: ea = qa1 - qa0
    else:           ea = qa1
    return eb - ea


def generate_ofi_signal(pair: str, prev: tuple, now: tuple, cfg: "Config") -> dict | None:
    """Sinyal OFI: order-flow imbalance memprediksi gerak harga jangka-pendek.
    Normalisasi OFI dgn depth (qb+qa) agar komparabel lintas pair. |nOFI|≥thr → sinyal.
    OFI>0 (tekanan beli) → BUY (kontinuasi flow). Hipotesis diuji PAPER."""
    raw = _ofi(prev, now)
    pb1, qb1, pa1, qa1 = now
    depth = qb1 + qa1
    if depth <= 0:
        return None
    nofi = raw / depth  # normalisasi
    thr = float(cfg.e2_ofi_thr)
    if abs(nofi) < thr:
        return None
    # KONTINUASI: OFI>0 (tekanan beli) → buy. REVERSI (default): OFI>0 → SELL
    #   (harga sudah terdorong naik oleh flow → balik). Kontinuasi terbukti <50% WR
    #   (momentum 37.5%, OFI 31.2%) → reversi default (e2_mom_reversion).
    if cfg.e2_mom_reversion:
        side = "sell" if nofi > 0 else "buy"
    else:
        side = "buy" if nofi > 0 else "sell"
    mag = abs(nofi) / thr
    grade = "S" if mag >= 2 else ("A" if mag >= 1.5 else "B")
    return {
        "pair": pair, "side": side, "grade": grade,
        "score": float(min(100.0, mag * 40.0)),
        "nofi": nofi, "obi": D(0), "funding_rate": D(0),
    }


class Engine2Directional:
    """Phase 2: Mesin sinyal DIREKSIONAL funding-rate + OBI (perps SoDEX).

    Strategi:
    • Masuk posisi saat sinyal kuat (funding squeeze + konfirmasi OBI).
    • Keluar via TP (take-profit), SL (stop-loss), atau timeout (30 mnt).
    • Paper-first default: harga simulasi mid+1pip; live butuh TE_E2_DIR_LIVE=1.
    • Budget keras $10: auto-HALT bila rugi kumulatif ≥ e2_dir_budget.
    • Self-governing: bila WR terbukti, kalibrasi ulang secara periodik.
    • Akunting: setiap sinyal dicatat di e2_dir_signals (ledger jujur).

    Bukan market-maker; bukan churn volume. Tujuan: profit (T2 + T3) sehingga
    E2 dapat di-skala volumenya dengan dukungan profit (sesuai doktrin user).
    """

    def __init__(self, cfg: "Config", adapter: "ExchangeAdapter",
                 led: "Ledger", tg: "Telegram"):
        self.cfg = cfg
        self.x = adapter
        self.led = led
        self.tg = tg
        self._sig_id: int | None = None   # open signal id (in-memory cache)
        self._step_count: int = 0          # B22: counter utk log periodik
        self._last_route_skip_log = 0.0
        self._lev_set: set[str] = set()    # pair yang leverage-nya sudah di-set (cache)
        # E2 momentum (paper-first) state
        self._mom_price_cache: dict = {}   # {pair: (last_mid, last_ts)}
        self._mom_open: dict = {}          # {pair: (side, entry_px, entry_ts)}
        self._mom_pairs: list = []         # cached liquid pair list
        self._mom_pairs_ts: float = 0.0
        self._ofi_snap: dict = {}          # {pair: (bidPx,bidSz,askPx,askSz,ts)} utk OFI
        self._mom_log_path = str(Path(__file__).resolve().parent.parent / "data" / "e2_momentum_paper.jsonl")
        # Pre-Gain bridge state (ponytail: minimal state, bridge handles cache)
        self._pregain_last_scan: float = 0.0
        self._pregain_queue: list[dict] = []

    # ── PRE-GAIN BRIDGE: Top Loser → E2Dir SHORT signals (BEAR only) ──
    def feed_pregain_signals(self, force: bool = False) -> int:
        """Consume Pre-Gain Top Loser scan → antrekan sinyal SHORT ke E2Dir.
        Hanya aktif saat Intel+Sentiment regime = BEAR (E1 handle BULL).
        Return: jumlah sinyal baru yang diantrekan.
        Force=True: abaikan cooldown scan (utk testing)."""
        if not self.cfg.e2_dir_enabled:
            return 0
        # Cooldown: scan tiap 15 menit (Pre-Gain cache TTL 5 menit, kita lebih konservatif)
        now = time.time()
        if not force and now - self._pregain_last_scan < 900:
            return 0
        self._pregain_last_scan = now
        try:
            from anantara.pregain_bridge import get_bearish_signals
            signals = get_bearish_signals(
                min_score=self.cfg.e2_pregain_min_score,
                max_signals=self.cfg.e2_pregain_max_signals,
            )
        except Exception as e:
            logging.warning("E2Dir Pre-Gain bridge error: %s", e)
            return 0
        if not signals:
            return 0
        # Queue signals (replace stale, keep fresh)
        self._pregain_queue = signals
        # S8 fix (audit 06-Okt-2026): _consume_pregain_signal() TIDAK PERNAH
        # dipanggil dari manapun (dead code) -- antrean ini belum tersambung
        # ke eksekusi apa pun. Log lama ("N signals queued") menyesatkan,
        # seolah akan dieksekusi. Jujur: hanya observasi, BELUM actionable.
        logging.info("E2Dir Pre-Gain: %d sinyal SHORT ter-scan (regime=BEAR) — "
                     "OBSERVASI SAJA, konsumer eksekusi belum aktif", len(signals))
        for s in signals[:3]:
            logging.info("  Pre-Gain → %s score=%d chg=%+.1f%%", s['pair'], s['score'], s['chg_pct'])
        return len(signals)

    def _consume_pregain_signal(self) -> dict | None:
        """Pop satu sinyal Pre-Gain dari antrean utk dieksekusi."""
        if not self._pregain_queue:
            return None
        # Cek masih valid (regime masih BEAR, sinyal < 30 menit)
        now = time.time()
        while self._pregain_queue:
            sig = self._pregain_queue[0]
            if now - sig.get('ts', 0) > 1800:  # 30 menit → stale
                self._pregain_queue.pop(0)
                continue
            return self._pregain_queue.pop(0)
        return None

    # ── E2 MOMENTUM PAPER SCANNER (high-frequency signal validation) ──
    def _mom_log(self, rec: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._mom_log_path), exist_ok=True)
            with open(self._mom_log_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass

    def scan_momentum_paper(self) -> None:
        """PAPER-ONLY momentum scanner — ukur WR sinyal momentum lintas banyak pair
        likuid SEBELUM live. TIDAK ada order nyata. Hasil → data/e2_momentum_paper.jsonl.

        Falsification-first: bila WR<50% setelah n≥30, hipotesis kontinuasi gugur.
        Promosi ke live HANYA via TE_E2_MOM_LIVE=1 + WR terbukti (keputusan terpisah).
        """
        if not self.cfg.e2_mom_enabled:
            return
        now = time.time()
        ofi_mode = (self.cfg.e2_sig_mode == "ofi")
        hold_s = self.cfg.e2_ofi_hold_s if ofi_mode else self.cfg.e2_mom_hold_s
        # 1) Tutup paper position yang sudah jatuh tempo
        for pair, (side, entry_px, entry_ts) in list(self._mom_open.items()):
            if now - entry_ts < hold_s:
                continue
            try:
                cur = float(self.x.book(pair).mid)  # float — OFI entry_px juga float (cegah Decimal-float)
            except Exception:
                continue
            ep = float(entry_px)
            if ep <= 0:
                del self._mom_open[pair]; continue
            pnl_pct = ((cur - ep) / ep) * (1.0 if side == "buy" else -1.0)
            self._mom_log({
                "ts": now, "pair": pair, "side": side, "mode": self.cfg.e2_sig_mode,
                "entry_px": float(entry_px), "exit_px": float(cur),
                "pnl_pct": pnl_pct, "win": pnl_pct > 0,
                "hold_s": round(now - entry_ts, 1),
            })
            del self._mom_open[pair]
        # 2) Buka sinyal baru bila slot tersedia
        if len(self._mom_open) >= self.cfg.e2_mom_max_open:
            return
        if not self._mom_pairs or now - self._mom_pairs_ts > 600:
            self._mom_pairs = _scan_liquid_perps(
                self.x, self.cfg.e2_mom_min_vol24h, self.cfg.e2_mom_top_n)
            self._mom_pairs_ts = now
        if ofi_mode:
            # OFI: 1 panggilan tickers → snapshot semua pair, hitung OFI vs snapshot lalu
            snaps = _fetch_perp_snapshots(self.x)
            for pair in self._mom_pairs:
                if pair in self._mom_open or pair not in snaps:
                    continue
                cur_snap = snaps[pair]  # (bpx,bsz,apx,asz)
                prev = self._ofi_snap.get(pair)
                self._ofi_snap[pair] = cur_snap + (now,)
                if prev is None or now - prev[4] < self.cfg.e2_mom_min_dt:
                    if prev is None:
                        pass  # belum ada acuan
                    else:
                        self._ofi_snap[pair] = prev  # tahan acuan hingga dt cukup
                    continue
                sig = generate_ofi_signal(pair, prev[:4], cur_snap, self.cfg)
                if sig:
                    entry_px = (cur_snap[0] + cur_snap[2]) / 2.0  # mid
                    self._mom_open[pair] = (sig["side"], entry_px, now)
                    if len(self._mom_open) >= self.cfg.e2_mom_max_open:
                        break
        else:
            for pair in self._mom_pairs:
                if pair in self._mom_open:
                    continue
                sig = generate_momentum_signal(self.x, pair, self.cfg, self._mom_price_cache)
                if sig:
                    entry_px = self._mom_price_cache.get(pair, (None,))[0]
                    if entry_px:
                        self._mom_open[pair] = (sig["side"], entry_px, now)
                        if len(self._mom_open) >= self.cfg.e2_mom_max_open:
                            break

    @staticmethod
    def momentum_paper_wr(log_path: str) -> dict:
        """Hitung WR + avg PnL dari paper log momentum (untuk gate promosi)."""
        try:
            lines = [json.loads(x) for x in open(log_path) if x.strip()]
        except Exception:
            return {"n": 0, "wr": 0.0, "avg_pnl_pct": 0.0}
        n = len(lines)
        if n == 0:
            return {"n": 0, "wr": 0.0, "avg_pnl_pct": 0.0}
        wins = sum(1 for r in lines if r.get("win"))
        avg = sum(r.get("pnl_pct", 0.0) for r in lines) / n
        return {"n": n, "wr": wins / n, "avg_pnl_pct": avg}

    def _route_key(self, suffix: str) -> str:
        return f"e2_route_{suffix}"

    def _route_disabled_until(self) -> float:
        try:
            return float(self.led.get_state(self._route_key("disabled_until"), "0"))
        except Exception:
            return 0.0

    def _route_cooldown_active(self) -> bool:
        until = self._route_disabled_until()
        if until <= time.time():
            return False
        if time.time() - self._last_route_skip_log > 60:
            logging.error("E2Dir perps route cooldown active for %.0fs — new entries skipped",
                          until - time.time())
            self._last_route_skip_log = time.time()
        return True

    def _record_route_failure(self, reason: str) -> None:
        now = time.time()
        first = float(self.led.get_state(self._route_key("first_failure_ts"), "0"))
        count = int(self.led.get_state(self._route_key("failure_count"), "0"))
        if first <= 0 or now - first > self.cfg.e2_route_fail_window_s:
            first = now
            count = 0
        count += 1
        self.led.set_state(self._route_key("first_failure_ts"), D(str(first)))
        self.led.set_state(self._route_key("failure_count"), D(str(count)))
        if count >= self.cfg.e2_route_max_failures:
            until = now + self.cfg.e2_route_cooldown_s
            self.led.set_state(self._route_key("disabled_until"), D(str(until)))
            self.led.set_state(self._route_key("first_failure_ts"), D("0"))
            self.led.set_state(self._route_key("failure_count"), D("0"))
            logging.error(
                "E2Dir perps route disabled for %ds after %d failures in %ds; last=%s",
                self.cfg.e2_route_cooldown_s,
                count,
                self.cfg.e2_route_fail_window_s,
                reason[:160],
            )

    def _record_route_success(self) -> None:
        self.led.set_state(self._route_key("first_failure_ts"), D("0"))
        self.led.set_state(self._route_key("failure_count"), D("0"))

    def budget_ok(self) -> bool:
        """True bila rugi kumulatif masih di bawah cap keras."""
        return self.led.e2_dir_budget_spent() < self.cfg.e2_dir_budget

    def edge_ok(self) -> tuple[bool, str]:
        """True bila WR terbukti (n≥min_n, WR > breakeven 50%).
        K3 fix (audit 06-Okt-2026): LIVE data kurang → HALT (fail-closed) —
        jangan trading uang nyata tanpa edge terbukti. PAPER/riset tetap
        fail-open supaya sampel bisa terkumpul (bootstrap)."""
        _scan_pair = self.cfg.e2_dir_pair or None  # B23: "" → None (semua pair)
        st = self.led.e2_dir_stats(_scan_pair)
        n = st["n"]
        if n < self.cfg.e2_dir_min_n:
            if self.cfg.e2_dir_live_enabled:
                return False, f"LIVE HALT: data kurang (n={n}<{self.cfg.e2_dir_min_n}) — edge belum terbukti"
            return True, f"data kurang (n={n}<{self.cfg.e2_dir_min_n}) — fail-open (paper/riset)"
        wr = st["win_rate"]
        if wr is None or wr < D("0.40"):
            return False, f"WR={float(wr)*100:.1f}%<40% dengan n={n} — HALT"
        return True, f"WR={float(wr)*100:.1f}% n={n} — OK"

    def step(self) -> bool:
        """Satu siklus: kelola posisi terbuka DAN cari sinyal baru bila ada slot.
        B29: Dukung hingga 3 sinyal serentak (pair berbeda) → kumpulkan data 3× lebih cepat.
        Return True bila ada aksi (buka/tutup posisi)."""
        if not self.budget_ok():
            logging.warning("E2Dir HALT: budget $%.2f habis (rugi $%.4f)",
                            float(self.cfg.e2_dir_budget),
                            float(self.led.e2_dir_budget_spent()))
            return False

        # B23: pair dinamis — None = scan semua; non-empty = fixed pair.
        _scan_pair = self.cfg.e2_dir_pair or None  # "" → None (scan semua)

        # B29: Kelola SEMUA posisi terbuka (concurrent — bukan hanya satu).
        # Max 3 sinyal serentak: cukup untuk mempercepat akumulasi data 3×
        # tanpa risiko budget terlalu tersebar.
        _MAX_CONCURRENT = 3
        open_poses = self.led.e2_dir_open_signals()
        acted = False
        for pos in open_poses:
            acted |= self._manage_position(pos)

        # B29: Slot penuh → tidak perlu cari sinyal baru siklus ini
        if len(open_poses) >= _MAX_CONCURRENT:
            return acted

        if self._route_cooldown_active():
            return acted

        # Ada slot kosong → cek edge gate lalu cari sinyal baru
        ok, reason = self.edge_ok()
        if not ok:
            logging.info("E2Dir gate: %s", reason)
            return acted

        sig = generate_directional_signal(self.x, _scan_pair, self.cfg)
        self._step_count += 1
        if sig is None:
            # B22: log periodik tiap 60 step (~3 menit) agar observable tanpa spam
            if self._step_count % 60 == 0:
                st = self.led.e2_dir_stats(_scan_pair)
                spent = self.led.e2_dir_budget_spent()
                logging.info(
                    "E2Dir watch #%d: tidak ada sinyal (n=%d WR=%s budget_sisa=$%.2f "
                    "concurrent=%d)",
                    self._step_count, st["n"],
                    f"{float(st['win_rate'])*100:.1f}%" if st["win_rate"] else "N/A",
                    float(self.cfg.e2_dir_budget - spent), len(open_poses))
            return acted

        # B33: skip pair yang sedang di-blacklist (WR buruk, cooldown 6h)
        if self.led.e2_dir_pair_is_blacklisted(sig["pair"]):
            logging.info("B33: pair %s di-blacklist — skip sinyal ini", sig["pair"])
            return acted

        # B29: Pastikan pair belum punya posisi terbuka (hindari duplikat per pair)
        if self.led.e2_dir_open_signal(sig["pair"]):
            logging.info("E2Dir B29: pair %s sudah punya posisi terbuka — skip",
                         sig["pair"])
            return acted

        return acted | self._open_position(sig)

    def _open_position(self, sig: dict) -> bool:
        """Buka posisi direksional berdasarkan sinyal."""
        if self._route_cooldown_active():
            return False

        pair = sig["pair"]
        side = sig["side"]
        try:
            bk = self.x.book(pair)
            mid = bk.mid
        except Exception as e:
            self._record_route_failure(f"e2dir_book_unavailable: {e}")
            logging.warning("E2Dir book() gagal: %s", e)
            return False

        size_usd = self.cfg.e2_dir_size_usd
        qty = size_usd / mid

        if self.cfg.e2_dir_live_enabled and hasattr(self.x, "_sodex"):
            # LEVERAGE: set sebelum entry → notional = margin × leverage (pengganda volume).
            # SoDEX TOLAK ubah leverage saat ADA posisi terbuka pada pair → set sekali
            # per pair (cache), skip bila sudah di-set. CLI balas TEKS ("leverage
            # updated"), bukan JSON → pakai subprocess langsung, jangan via _sodex (JSON).
            lev = max(1, int(self.cfg.e2_dir_leverage))
            if lev > 1 and pair not in self._lev_set:
                try:
                    import subprocess as _sp
                    _bin = getattr(self.x, "_sodex_bin", "bin/sodex")
                    r = _sp.run([_bin, "leverage", pair, str(lev), "--mode", "isolated"],
                                capture_output=True, text=True, timeout=10, env=dict(os.environ))
                    out = (r.stdout + r.stderr).lower()
                    if "leverage updated" in out or "open position" in out:
                        self._lev_set.add(pair)  # set ATAU sudah ada posisi (pakai lev existing)
                except Exception as e:
                    logging.debug("E2Dir set leverage %sx %s: %s", lev, pair, e)
            # Live entry via MARKET IOC (DITEMUKAN 2026-06-21): limit-GTC di touch perps
            # SoDEX → oid=0 (crossing ditolak). Market+IOC terisi ANDAL (terbukti tutup
            # ENA orphan). Fallback ke place_post_only bila adapter lama tak punya method.
            entry_px = bk.ask if side == "buy" else bk.bid
            if hasattr(self.x, "place_market_ioc"):
                o = self.x.place_market_ioc(pair, side, qty, mid, reduce_only=False)
            else:
                o = self.x.place_post_only(pair, side, entry_px, qty)
            if not o or not o.oid or o.oid == "0":
                self._record_route_failure("e2dir_order_rejected_oid0")
                self.led.e2_dir_pair_blacklist(pair, 15 * 60)
                logging.warning("B41 E2Dir: order gagal terpasang %s (oid kosong) — cooldown 15m", pair)
                return False
            if o.filled >= qty:
                # Market IOC sudah terisi penuh (skip poll yg di-neuter B9)
                qty = o.filled
                entry_px = o.price
            else:
                # Jalur limit lama: poll singkat
                filled = D(0)
                deadline = time.time() + 15
                while time.time() < deadline and filled < qty:
                    inc = self.x.poll_fill(o)
                    filled += inc
                    if filled >= qty * D("0.9"):
                        break
                    time.sleep(0.5)
                if filled < qty * D("0.3"):
                    self.x.cancel(o)
                    self._record_route_failure("e2dir_insufficient_fill")
                    return False
                qty = filled
                entry_px = o.price
            self._record_route_success()
        else:
            # Paper: simulasi fill di mid price (konservatif)
            entry_px = mid

        sig_id = self.led.e2_dir_open(
            pair, side, sig["grade"],
            sig["funding_rate"], sig["obi"], entry_px, qty)
        self._sig_id = sig_id

        mode = "LIVE" if self.cfg.e2_dir_live_enabled else "PAPER"
        # S9 fix (audit 06-Okt-2026): obi kini None (tak tersedia, lihat
        # generate_directional_signal) -- "n/a" di log, bukan crash float(None).
        obi_disp = f"{float(sig['obi']):+.3f}" if sig["obi"] is not None else "n/a"
        logging.info(
            "E2Dir OPEN [%s]: %s %s grade=%s fr=%+.5f obi=%s "
            "entry=%.8f qty=%.2f size=$%.2f",
            mode, side, pair, sig["grade"],
            float(sig["funding_rate"]), obi_disp,
            float(entry_px), float(qty), float(entry_px * qty))
        return True

    def _manage_position(self, pos: dict) -> bool:
        """Kelola posisi terbuka: cek SL/TP/timeout."""
        pair      = pos["pair"]
        side      = pos["side"]
        entry_px  = pos["entry_px"]
        qty       = pos["qty"]
        opened_ts = pos["opened_ts"]
        sig_id    = pos["id"]

        # Hitung TP dan SL
        sl_frac = self.cfg.e2_dir_sl_pct
        tp_frac = self.cfg.e2_dir_tp_pct
        if side == "buy":
            sl_px = entry_px * (1 - sl_frac)
            tp_px = entry_px * (1 + tp_frac)
        else:  # sell
            sl_px = entry_px * (1 + sl_frac)
            tp_px = entry_px * (1 - tp_frac)

        # Harga sekarang
        try:
            bk = self.x.book(pair)
            cur_px = bk.mid
        except Exception:
            return False  # tidak bisa ambil harga → skip, coba lagi nanti

        # Cek timeout
        opened_dt = datetime.fromisoformat(opened_ts.replace("Z", "+00:00"))
        age_s = (datetime.now(UTC) - opened_dt).total_seconds()
        timeout = age_s > self.cfg.e2_dir_hold_s

        # Tentukan exit reason
        if side == "buy":
            sl_hit = cur_px <= sl_px
            tp_hit = cur_px >= tp_px
        else:
            sl_hit = cur_px >= sl_px
            tp_hit = cur_px <= tp_px

        reason = None
        exit_px = cur_px
        if tp_hit:
            reason = "tp"
        elif sl_hit:
            reason = "sl"
        elif timeout:
            reason = "timeout"

        if reason is None:
            return False  # posisi masih berjalan

        # K4 fix (audit 06-Okt-2026): LIVE harus KIRIM order close NYATA ke
        # exchange sebelum ledger ditutup — sebelumnya cuma hitung PnL lokal
        # dari mid book, posisi di exchange tetap terbuka selamanya. Gagal/
        # partial fill → JANGAN tutup ledger, biar retry siklus depan (sama
        # disiplin dgn K2: tak pernah klaim close sukses tanpa konfirmasi).
        if self.cfg.e2_dir_live_enabled:
            close_side = "sell" if side == "buy" else "buy"
            try:
                if hasattr(self.x, "place_market_ioc"):
                    o = self.x.place_market_ioc(pair, close_side, qty, exit_px, reduce_only=True)
                else:
                    o = self.x.place_post_only(pair, close_side, exit_px, qty)
            except Exception as e:
                logging.error("E2Dir CLOSE LIVE gagal kirim order %s %s: %s — posisi TETAP terbuka, retry",
                               pair, reason, e)
                return False
            if not o or not o.oid or o.oid == "0" or o.filled < qty:
                logging.error(
                    "E2Dir CLOSE LIVE %s %s: order gagal/partial (oid=%s filled=%s/%s) — "
                    "posisi TETAP terbuka, retry siklus depan",
                    pair, reason, getattr(o, "oid", None), getattr(o, "filled", None), qty)
                return False
            exit_px = o.price  # harga fill nyata, bukan mid lokal

        # Hitung PnL (sederhana, sebelum fee untuk paper; eksakta saat live)
        if side == "buy":
            gross = (exit_px - entry_px) * qty
        else:
            gross = (entry_px - exit_px) * qty
        # Kurangi fee TAKER perps (entry + exit). E2Dir pakai IOC/taker → fee lebih tinggi.
        # B20: pakai perp_taker_fee (0.02%) bukan perp_maker_fee (0.0108%).
        fee = entry_px * qty * self.cfg.perp_taker_fee * D("2")
        pnl = gross - fee

        self.led.e2_dir_close(sig_id, exit_px, pnl, reason)
        self._sig_id = None

        pnl_sign = "✅" if pnl > 0 else "🔴"
        logging.info(
            "E2Dir CLOSE [%s]: %s %s reason=%s entry=%.8f exit=%.8f pnl=$%+.5f",
            "LIVE" if self.cfg.e2_dir_live_enabled else "PAPER",
            side, pair, reason,
            float(entry_px), float(exit_px), float(pnl))
        st = self.led.e2_dir_stats(pair)

        # B33: evaluasi per-pair WR setelah close — blacklist bila sering kalah
        _B33_MIN_N    = 5     # butuh minimal n close untuk evaluasi pair
        _B33_WR_FLOOR = 0.35  # WR < 35% → cooldown
        _B33_COOLDOWN = 6 * 3600  # 6 jam
        pair_n, pair_wr = self.led.e2_dir_pair_wr(pair, last_n=10)
        if pair_n >= _B33_MIN_N and pair_wr is not None and pair_wr < _B33_WR_FLOOR:
            self.led.e2_dir_pair_blacklist(pair, _B33_COOLDOWN)
            logging.warning(
                "B33 BLACKLIST %s: WR=%.1f%% n=%d (< %.0f%% floor) — cooldown 6h",
                pair, pair_wr * 100, pair_n, _B33_WR_FLOOR * 100)

        self.tg.send(
            f"{pnl_sign} E2Dir CLOSE [{reason.upper()}]: {side} {pair}\n"
            f"PnL: ${float(pnl):+.4f}  entry={float(entry_px):.6f}  exit={float(exit_px):.6f}\n"
            f"Total: n={st['n']} WR={float(st['win_rate'] or 0)*100:.1f}%"
            f" PnL_total=${float(st['total_pnl']):+.4f}"
        )
        return True


# ============================== 9. ORKESTRATOR ===============================

class Orchestrator:
    def __init__(self, cfg: Config, live: bool):
        self.cfg = cfg
        self.tg = Telegram(cfg)
        self.led = Ledger(cfg.db_path)
        self.guards = Guards(cfg, self.led, self.tg)
        self.treasury = Treasury(cfg, self.led, self.guards)
        self.x: ExchangeAdapter = SodexLiveAdapter(cfg) if live else PaperAdapter(cfg)
        self.live = live
        self._stop = False
        # ---- G0: verifikasi pair & mode hedge ----
        pairs = set(self.x.list_pairs())
        if cfg.spot_pair not in pairs:
            raise SystemExit(f"G0 GAGAL: {cfg.spot_pair} tidak ada di pair list")
        hedge = cfg.hedge_perp in pairs
        if not hedge:
            self.tg.send(f"⚠️ G0: {cfg.hedge_perp} tidak tersedia — hedge OFF, "
                         f"inventori dibatasi ${cfg.e1_inv_cap_per_pair}")
        # Engine-1 untuk pair utama (PEPE)
        self.e1 = Engine1Flywheel(cfg, self.x, self.led, self.guards, self.tg, hedge)

        # ── STARTUP: bersihkan orphaned orders & ghost positions ──
        if live:
            self._startup_cleanup()
            self._reconcile_e2_positions()  # crash-recovery: close any E2 ghosts
            ghost_count = self.x.sweep_perps_ghosts()
            if ghost_count > 0:
                self.tg.send(f"👻 Ghost sweep: {ghost_count} positions closed")
                logging.info("Ghost sweep: %d positions closed", ghost_count)
        
        # Fase 1: Engine-1B untuk pair kedua (SHIB) — tanpa hedge, spread lebih kecil
        self._has_pair2 = cfg.spot_pair_2 and cfg.spot_pair_2 in pairs
        if self._has_pair2:
            self.tg.send(f"✅ G0: {cfg.spot_pair_2} tersedia — dual-pair mode aktif")
            self.e1b = Engine1Flywheel(cfg, self.x, self.led, self.guards, self.tg, False, pair=cfg.spot_pair_2)
        else:
            self.e1b = None
            if cfg.spot_pair_2:
                self.tg.send(f"⚠️ G0: {cfg.spot_pair_2} tidak tersedia — single-pair mode")
        
        # Jun 16: Engine-1C untuk pair ketiga (SOL/USDC) — high notional, tight spread
        self._has_pair3 = cfg.spot_pair_3 and cfg.spot_pair_3 in pairs
        if self._has_pair3:
            self.tg.send(f"✅ G0: {cfg.spot_pair_3} tersedia — triple-pair mode aktif")
            self.e1c = Engine1Flywheel(cfg, self.x, self.led, self.guards, self.tg, False, pair=cfg.spot_pair_3)
        else:
            self.e1c = None
            if cfg.spot_pair_3:
                self.tg.send(f"⚠️ G0: {cfg.spot_pair_3} tidak tersedia")
        
        # Jun 16: Engine-1D untuk pair keempat (XLM/USDC) — wide spread 0.137%
        self._has_pair4 = cfg.spot_pair_4 and cfg.spot_pair_4 in pairs
        if self._has_pair4:
            self.tg.send(f"✅ G0: {cfg.spot_pair_4} tersedia — quad-pair mode aktif")
            self.e1d = Engine1Flywheel(cfg, self.x, self.led, self.guards, self.tg, False, pair=cfg.spot_pair_4)
        else:
            self.e1d = None
            if cfg.spot_pair_4:
                self.tg.send(f"⚠️ G0: {cfg.spot_pair_4} tidak tersedia")
        
        # Build list of all spot engines for iteration
        self._spot_engines: list[Engine1Flywheel] = [self.e1]
        if self.e1b: self._spot_engines.append(self.e1b)
        if self.e1c: self._spot_engines.append(self.e1c)
        if self.e1d: self._spot_engines.append(self.e1d)
        
        # ── B13: rekonsiliasi balance-delta (live) — kebenaran tunggal ──
        self._usdc_prev: Decimal | None = None
        self._last_monitor_tg = 0.0   # B16: throttle Telegram monitor (1 jam)
        if live:
            for eng in self._spot_engines:
                eng.reconcile_mode = True   # fill di-catat dari saldo riil, bukan poll_fill
            # B19: inisialisasi timestamp mulai eksperimen (sekali, saat pertama aktif)
            if cfg.e1_research_enabled and self.led.get_state("e1_research_start_ts") <= 0:
                self.led.set_state("e1_research_start_ts", Decimal(str(time.time())))
                self.tg.send(f"🔬 B19 EKSPERIMEN MULAI: quote spread ≥ "
                             f"{float(cfg.e1_research_min_spread)*10000:.0f}bps, "
                             f"budget ${float(cfg.e1_research_budget):.2f}, target n={cfg.e1_research_target_n}")
                logging.warning("B19 eksperimen MULAI: min_spread=%.4f budget=%.2f n=%d",
                                float(cfg.e1_research_min_spread), float(cfg.e1_research_budget),
                                cfg.e1_research_target_n)

        # ── SYNC inventory AFTER all engines created ──
        if live:
            self._sync_inventory_from_exchange(force=True)
        
        self.e2 = Engine2Perps(cfg, self.x, self.led, self.guards, self.treasury, self.tg)
        # Jun 17: Multi-perps pure maker — 3 profitable pairs
        self.e2b = Engine2Perps(cfg, self.x, self.led, self.guards, self.treasury, self.tg, pair=cfg.churn_perp_2) if cfg.churn_perp_2 else None
        self.e2c = Engine2Perps(cfg, self.x, self.led, self.guards, self.treasury, self.tg, pair=cfg.churn_perp_3) if cfg.churn_perp_3 else None
        self._perps_engines = [self.e2]
        if self.e2b: self._perps_engines.append(self.e2b)
        if self.e2c: self._perps_engines.append(self.e2c)
        self._perps_idx = 0
        # Phase 2: Directional engine (disabled by default)
        self.e2_dir = Engine2Directional(cfg, self.x, self.led, self.tg) \
            if (cfg.e2_dir_enabled or cfg.e2_mom_enabled) else None
        signal.signal(signal.SIGINT, self._sig)
        signal.signal(signal.SIGTERM, self._sig)
    def _sig(self, *_):
        self._stop = True
    def _startup_cleanup(self):
        """Batalkan semua order spot terbuka saat startup.
        Mencegah orphaned orders (dari sesi sebelumnya) double-post dengan order baru."""
        try:
            n = self.x.cancel_all_spot_orders()
            if n > 0:
                self.tg.send(f"🧹 Startup cleanup: {n} orphaned spot order dibatalkan")
                logging.info("startup_cleanup: %d orphaned spot orders cancelled", n)
            time.sleep(1.0)  # beri waktu exchange memproses pembatalan
        except Exception as e:
            logging.warning("startup_cleanup gagal: %s — lanjut tanpa cleanup", e)

    def _reconcile_e2_positions(self):
        """Startup: cek Ledger untuk E2 perps positions yang terbuka tapi belum tertutup.
        Ini terjadi jika daemon crash setelah leg1 fill tapi sebelum leg2 close.
        Untuk setiap unclosed record: sweep ghost on that pair to close the position."""
        cleared = self.led.e2_clear_nonrecoverable_open_positions()
        if cleared:
            logging.warning("E2 RECONCILE: cleared %d non-recoverable zero/empty local record(s)", cleared)
            self.tg.send(f"🧹 E2 Reconcile: {cleared} ghost lokal qty=0 dibersihkan tanpa sweep")

        open_recs = self.led.e2_get_open_positions()
        if not open_recs:
            return
        logging.warning("E2 RECONCILE: %d unclosed position record(s) found", len(open_recs))
        self.tg.send(f"⚠️ E2 Reconcile: {len(open_recs)} posisi perps belum tertutup (crash recovery)")
        for rec in open_recs:
            pair = rec["pair"]
            logging.info("E2 reconcile: sweeping pair=%s entry_px=%s qty=%s opened=%s",
                         pair, rec["entry_px"], rec["qty"], rec["opened_ts"])
            try:
                swept = self.x.sweep_perps_ghosts()
                if swept > 0:
                    self.tg.send(f"✅ E2 Reconcile: swept {swept} ghost position(s) on {pair}")
                else:
                    # sweep_perps_ghosts sweeps ALL pairs — if 0, position already closed
                    self.tg.send(f"ℹ️ E2 Reconcile: {pair} — no ghost found (already closed?)")
            except Exception as e:
                logging.error("E2 reconcile error on %s: %s", pair, e)
            finally:
                # Always clear the DB record: either swept or already gone
                self.led.e2_clear_open(rec["id"])

    def _sync_inventory_from_exchange(self, force: bool = False):
        """Samakan inv_qty engine dengan saldo exchange sebenarnya.
        Ini mencegah engine trading tanpa sadar inventory menumpuk.
        force=True: selalu update tanpa threshold (dipakai saat startup)."""
        try:
            bal = self.x.balance()
            # Map coin name → pair
            coin_map = {
                "PEPE/USDC": ("vPEPE", "vUSDC"),
                "SHIB/USDC": ("vSHIB", "vUSDC"),
                "SOL/USDC": ("vSOL", "vUSDC"),   # Jun 16: 3rd pair
                "XLM/USDC": ("vXLM", "vUSDC"),    # Jun 16: 4th pair
            }
            for pair, (base_coin, _) in coin_map.items():
                qty = bal.get(base_coin, D(0))
                # Tentukan engine mana — iterate spot engine list
                eng = None
                for e in self._spot_engines:
                    if e.pair == pair:
                        eng = e; break
                if eng is None:
                    continue
                bk = self.x.book(pair)
                # DONT CAP: engine harus tahu inventori sebenarnya
                # Cap di _place_two_sided() yang membatasi ukuran quote
                inv_usd = qty * bk.mid
                tracked_usd = eng._inv_usd(bk.mid)
                diff = abs(inv_usd - tracked_usd)
                # Update jika: force (startup) ATAU beda >$5 ATAU beda >10%
                should_sync = (
                    force
                    or diff > D("5")
                    or (tracked_usd > 0 and diff / tracked_usd > D("0.1"))
                )
                if should_sync:
                    logging.info("INV SYNC: %s exchange=%s qty tracked=%s → set to %s",
                                 pair, float(qty), float(eng.inv_qty), float(qty))
                    self.tg.send(f"🔄 SYNC: {pair} inv {qty:,.0f} qty (${inv_usd:.2f}) — "
                                 f"sebelumnya tercatat {eng.inv_qty:,.0f} qty (${tracked_usd:.2f})")
                    eng.inv_qty = qty
                    # Reset buy_q — kita tidak tahu cost basis order sebelumnya
                    eng.buy_q.clear()
                    # B45: jangan set _inv_started langsung. Restore timestamp
                    # pair-scoped bila ada; jika tidak ada, mulai jam inventori
                    # untuk pair ini dari waktu sync.
                    if qty > 0:
                        if not eng._restore_inv_started():
                            eng._set_inv_started(time.time())
                    else:
                        eng._set_inv_started(None)
        except Exception as e:
            logging.warning("Inventory sync gagal: %s", e)

    _COIN_MAP = {
        "PEPE/USDC": "vPEPE", "SHIB/USDC": "vSHIB",
        "SOL/USDC": "vSOL", "XLM/USDC": "vXLM",
    }

    def _reconcile_all_from_balance(self):
        """B13: Rekonsiliasi SEMUA engine dari saldo riil — kebenaran tunggal.

        Membaca balance sekali, menghitung delta per-coin, mengatribusikan delta
        USDC ke engine yang bergerak (eksak bila TEPAT SATU pair bergerak; mid bila
        ambigu), lalu memanggil engine.reconcile_delta() untuk merekam fill/RT
        dengan harga efektif (fee ter-bake). Ini menggantikan deteksi-fill via
        poll_fill yang tak andal (CLI tanpa order-history).
        """
        try:
            bal = self.x.balance()
        except Exception as e:
            logging.warning("reconcile: balance() gagal: %s — skip siklus ini", e)
            return
        usdc_now = bal.get("vUSDC", D(0))

        # Snapshot mid per engine (cache untuk hindari panggilan ganda)
        engines = []
        for eng in self._spot_engines:
            coin = self._COIN_MAP.get(eng.pair)
            if not coin:
                continue
            try:
                mid = self.x.book(eng.pair).mid
            except Exception:
                continue
            real = bal.get(coin, D(0))
            engines.append((eng, real, mid))

        # Baseline pertama: seed tanpa mencatat fill (hindari delta palsu dari 0)
        if self._usdc_prev is None:
            for eng, real, mid in engines:
                eng.seed_baseline(real, mid)
            self._usdc_prev = usdc_now
            # Rekam timestamp aktivasi B13 SEKALI (untuk monitor pisahkan data
            # jujur post-B13 dari RT phantom pra-B13). Disimpan epoch (numerik).
            if self.led.get_state("b13_activated_ts") <= 0:
                self.led.set_state("b13_activated_ts", Decimal(str(time.time())))
                logging.info("B13 aktivasi dicatat: %s", datetime.now(UTC).isoformat())
            logging.info("reconcile: baseline di-seed (USDC=%s)", float(usdc_now))
            return

        # Engine yang bergerak (delta > dust)
        movers = [(eng, real, mid) for (eng, real, mid) in engines
                  if abs(real - eng.inv_qty) * mid >= Engine1Flywheel.RECONCILE_DUST_USD]
        d_usdc_total = usdc_now - self._usdc_prev

        for eng, real, mid in engines:
            if len(movers) == 1 and movers[0][0] is eng:
                # Atribusi USDC EKSAK: hanya pair ini yang bergerak
                ev = eng.reconcile_delta(real, mid, d_usdc_total)
            else:
                # Ambigu (>1 pair atau non-mover) → mid sebagai aproksimasi
                ev = eng.reconcile_delta(real, mid, None)
            if ev and ev.get("rts", 0) > 0:
                logging.info("reconcile RT: %s %d RT, PnL=$%.5f (px=%.10f)",
                             ev["pair"], ev["rts"], float(ev.get("rt_pnl", 0)),
                             float(ev.get("price", 0)))
        self._usdc_prev = usdc_now

    def _sample_spreads(self):
        """B18: rekam spread per pair (pasif, NOL-RISIKO — hanya observasi orderbook)
        untuk riset edge E1. Tidak memengaruhi trading sama sekali."""
        try:
            rows = []
            now_iso = datetime.now(UTC).isoformat()
            for eng in self._spot_engines:
                try:
                    bk = self.x.book(eng.pair)
                    mid = bk.mid
                    if mid and mid > 0:
                        spread_bps = float((bk.ask - bk.bid) / mid * 10000)
                        rows.append({"ts": now_iso, "pair": eng.pair,
                                     "spread_bps": round(spread_bps, 3),
                                     "mid": float(mid)})
                except Exception:
                    continue
            if rows:
                os.makedirs(os.path.dirname(self.cfg.spread_path) or ".", exist_ok=True)
                with open(self.cfg.spread_path, "a") as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")
        except Exception as e:
            logging.debug("sample_spreads gagal: %s", e)

    def equity_estimate(self):
        """G4 FIX 2026-09-27 (crash-loop 48× restart 26-Sep): LIVE memakai HANYA
        ekuitas akun riil (satu sumber kebenaran, sebanding antar-waktu).
        Ledger TIDAK dicampur — ledger $66,15 vs riil $61,63 (overstatement $4,5)
        dipakai ratchet → drawdown SEMU 6,8% ≥ 6% → HARD STOP berulang.
        Akun gagal dibaca → None (check_equity skip; fail-SKIP bukan fail-STOP
        salah). Paper/dry-run tetap ledger (tidak ada akun)."""
        if self.live:
            eq = self.x.account_equity()
            self._last_equity_source = "live_account" if eq is not None else "live_account_unavailable"
            return eq
        self._last_equity_source = "ledger"
        wk0 = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        return self.cfg.capital_usd + self.led.total_profit_since(wk0)
    def run(self, max_iter: int | None = None, sleep_s: float = 1.0):
        mode = "LIVE" if self.live else "DRY-RUN (paper)"
        pair_info = " + ".join(e.pair for e in self._spot_engines)
        self.tg.send(f"🚀 Twin-Engine start [{mode}] — {pair_info} — allowance E2: "
                     f"${self.treasury.allowance():.2f}")
        i = 0
        _hb = time.time()  # self-watchdog: timer heartbeat terakhir
        _HB_TIMEOUT = 300  # 5 menit tanpa heartbeat → force restart (was 900, tightened for hang bug)
        try:
            while not self._stop and (max_iter is None or i < max_iter):
                i += 1
                # ── SELF-WATCHDOG: jika 5 menit tanpa progress, force exit ──
                if time.time() - _hb > _HB_TIMEOUT:
                    logging.error("SELF-WATCHDOG: daemon stuck >%ds — force exit", _HB_TIMEOUT)
                    self.tg.send(f"🆘 SELF-WATCHDOG: daemon stuck — force restart")
                    os._exit(1)
                if self.guards.in_event_window():
                    time.sleep(5); _hb = time.time(); continue
                # P2: skip bad hours (UTC 01-02 historically negative PnL)
                if self.cfg.e1_bad_hours and datetime.now(UTC).hour in self.cfg.e1_bad_hours:
                    time.sleep(30); _hb = time.time(); continue
                try:
                    # Per-step alarm timeout: prevents hang on any blocking call
                    self.e1.step()
                    _hb = time.time()  # step sukses → reset watchdog
                except Exception as e:
                    logging.warning("E1 step error (transient?): %s", e)
                    # RESET state: buang order rusak, fresh start next iter
                    for o in self.e1.orders:
                        try: self.x.cancel(o)
                        except Exception: pass
                    self.e1.orders.clear()
                    time.sleep(4)
                    continue
                # Fase 1: pair kedua di-step di iterasi ganjil (non-overlapping)
                # Step all additional spot engines (E1b, E1c, E1d, ...)
                for eng in self._spot_engines[1:]:  # skip E1 (already stepped above)
                    try:
                        eng.step()
                    except Exception as e:
                        logging.warning("%s step error: %s", eng.pair, e)
                        for o in eng.orders:
                            try: self.x.cancel(o)
                            except Exception: pass
                        eng.orders.clear()
                if i % self.cfg.e2_call_every == 0 and self.cfg.e2_enabled:  # B57: configurable freq
                    try:
                        # Alternate between perps pairs for volume diversification
                        eng = self._perps_engines[self._perps_idx % len(self._perps_engines)]
                        self._perps_idx += 1
                        eng.churn_cycle()
                    except Exception as e:
                        logging.warning("E2 churn error: %s", e)
                # Phase 2: directional engine — setiap 10 iter (~10-18s)
                if i % 10 == 0 and self.e2_dir is not None and self.cfg.e2_dir_enabled:
                    try:
                        self.e2_dir.step()
                    except Exception as e:
                        logging.warning("E2Dir step error: %s", e)
                # Pre-Gain Bridge: feed Top Loser → E2Dir SHORT (BEAR only, tiap ~15 min)
                if i % 150 == 0 and i > 0 and self.e2_dir is not None:
                    try:
                        self.e2_dir.feed_pregain_signals()
                    except Exception as e:
                        logging.warning("Pre-Gain bridge error: %s", e)
                # E2 momentum PAPER scanner — setiap 5 iter (~5-9s, sampling cukup sering
                # utk window dt 20-180s). Paper-only: tidak ada order nyata, ukur WR.
                if i % 5 == 0 and self.e2_dir is not None and self.cfg.e2_mom_enabled:
                    try:
                        self.e2_dir.scan_momentum_paper()
                    except Exception as e:
                        logging.warning("E2 momentum scan error: %s", e)
                if i % 10 == 0:
                    # S10 fix (audit 06-Okt-2026): jalur order live E2Perps/E2Dir
                    # (_rebalance_hedge, churn_cycle/_maker_leg) TIDAK panggil
                    # check_equity() langsung per-trade -- guard drawdown cuma
                    # global periodik di sini. Perketat interval 50->10 iterasi
                    # (~5x lebih sering) supaya jendela "belum ter-check" lebih
                    # kecil, tanpa restrukturisasi Engine2Perps/Directional.
                    _eq = self.equity_estimate()
                    self.guards.check_equity(_eq, self._last_equity_source)
                # B13: rekonsiliasi balance-delta tiap 5 iter (~5-9s). Membaca saldo
                # riil, merekam fill/RT dari delta (kebenaran tunggal — CLI tanpa
                # order-history). Menjaga inv_qty akurat (cap efektif) DAN mencatat
                # PnL RT jujur (fee ter-bake dari delta USDC). Menggantikan B12 sync
                # yang hanya overwrite + kliring buy_q (kehilangan sinyal PnL).
                if self.live and i % 5 == 0:
                    self._reconcile_all_from_balance()
                # Jun 17: Periodic ghost check (every 300 iter ~15 min)
                if self.live and i % 300 == 0 and i > 0:
                    ghost_count = self.x.sweep_perps_ghosts()
                    if ghost_count > 0:
                        logging.warning("Periodic ghost sweep: %d closed", ghost_count)
                if i % 30 == 0:
                    inv_info = f"E1 inv={self.e1.inv_qty:.0f}"
                    if self._has_pair2 and self.e1b:
                        inv_info += f" E1b inv={self.e1b.inv_qty:.0f}"
                    logging.info("💓 heartbeat #%d | %s | orders=%d | equity~$%s",
                                 i, inv_info, len(self.e1.orders),
                                 f"{float(e):.2f}" if (e := self.equity_estimate()) is not None else "?unavailable")
                    # B18: sampel spread (pasif, nol-risiko) untuk riset edge E1
                    if self.live:
                        self._sample_spreads()
                # B15: log net mingguan E1+E2 (metrik inti user) tiap ~300 iter
                if i % 300 == 0 and i > 0:
                    try:
                        ws = weekly_net_summary(self.led)
                        logging.info("📊 NET MINGGUAN E1+E2: E1=$%+.4f E2=$%+.4f NET=$%+.4f %s",
                                     float(ws["e1_profit"]), float(ws["e2_net"]),
                                     float(ws["combined_net"]),
                                     "✅on-track" if ws["on_track"] else "🔴E1<E2")
                    except Exception as e:
                        logging.debug("weekly_net log gagal: %s", e)
                # B16: snapshot Monitoring & Evaluasi OTONOM tiap ~600 iter (~15-20 mnt).
                # Berbasis DATA RIIL (balance) + ledger jujur. Persist ke JSONL (audit/tren).
                # Telegram throttled 1 jam. Selalu jalan (live) — monitoring kontinu.
                if self.live and i % 600 == 0 and i > 0:
                    try:
                        rep = build_monitor_report(self.cfg, self.x, self.led)
                        persist_monitor_snapshot(self.cfg, rep)
                        logging.info("📡 MONITOR: equity=$%s net_jujur=$%s vol=$%s verdict=%s",
                                     rep.get("real_equity"), rep.get("honest_net"),
                                     rep.get("vol_total_week"), rep.get("verdict"))
                        if time.time() - self._last_monitor_tg > 3600:
                            self._last_monitor_tg = time.time()
                            eq = rep.get("real_equity"); hn = rep.get("honest_net")
                            vt = rep.get("vol_total_week")
                            eq_s = f"${eq:.2f}" if eq is not None else "?"
                            hn_s = f"${hn:+.4f}" if hn is not None else "?"
                            vt_s = f"${vt:,.0f}" if vt is not None else "?"
                            cflag = " ⚠️tercemar-pra-B13" if rep.get("week_has_contaminated_data") else ""
                            self.tg.send(
                                f"📡 Monitor Twin-Engine (data riil)\n"
                                f"Ekuitas riil: {eq_s}\n"
                                f"Net JUJUR mgg: {hn_s}{cflag}\n"
                                f"Volume mgg: {vt_s}\n"
                                f"Verdict: {rep.get('verdict')}")
                    except Exception as e:
                        logging.debug("monitor snapshot gagal: %s", e)
                time.sleep(sleep_s * RNG.uniform(0.4, 1.8))
        except HardStop as e:
            logging.error("HARD STOP: %s", e)
            # AUDIT 29-Sep-2026: tulis penanda fail-closed saat hard-stop (drawdown/loss harian).
            # Fungsi ini sudah lama ADA tapi TAK PERNAH dipanggil → data/SAFETY_HALT tak pernah
            # dibuat → watchdog/komponen lain tak tahu hard-stop terjadi = fail-OPEN di rantai
            # safety. Test test_sodex_watchdog_policy menuntut pola ini sejak awal = regresi lama
            # yang suite merah selama ini (audit: 1 dari 58 kegagalan lama).
            write_safety_halt(str(e))
        finally:
            self.e1.shutdown()
            if self._has_pair2 and self.e1b:
                self.e1b.shutdown()
            # Cancel all perps orders on shutdown — prevent ghost positions
            # S5 fix (audit 06-Okt-2026): dulu 1 try/except membungkus SELURUH
            # blok (list+loop+cancel) lalu Telegram klaim "semua dibatalkan"
            # TANPA SYARAT walau exception terjadi. Sekarang: list & setiap
            # cancel diisolasi, HASIL NYATA dihitung sebelum lapor ke Telegram.
            _cancel_attempted = 0
            _cancel_failed = 0
            for eng in self._perps_engines:
                try:
                    orders = self.x._sodex_list(["orders", "list", "perps", "--format", "json"], timeout=10)
                except Exception as e:
                    logging.warning("shutdown cancel-all: gagal list order perps (%s): %s", eng.pair, e)
                    _cancel_failed += 1
                    continue
                for o in orders:
                    oid = str(o.get("orderID", ""))
                    sym = o.get("symbol", "")
                    sid = None
                    for pair, psid in self.x._SYMBOL_MAP.items():
                        if "-USD" in pair and pair.split("-")[0].upper() in sym.upper():
                            sid = psid; break
                    if not (oid and sid):
                        continue
                    _cancel_attempted += 1
                    try:
                        self.x._sodex(["orders", "cancel", "perps", "--symbol-id", str(sid),
                                      "--order-id", oid, "--format", "json"], timeout=10)
                    except Exception as e:
                        _cancel_failed += 1
                        logging.warning("shutdown cancel-all: order %s gagal dibatalkan: %s", oid, e)
            if _cancel_failed == 0:
                self.tg.send(f"⏹ Twin-Engine berhenti — {_cancel_attempted} order perps dibatalkan, ledger tersimpan.")
            else:
                self.tg.send(f"⚠️ Twin-Engine berhenti — cancel-all SEBAGIAN GAGAL "
                              f"({_cancel_failed} gagal dari {_cancel_attempted} percobaan) — "
                              f"CEK MANUAL order tersisa di exchange. Ledger tersimpan.")

# ====================== 10. REPORT SELASA (G1/G3) & STATUS ===================

def cmd_report(cfg: Config):
    """Jalankan tiap Selasa setelah 12:00 UTC: masukkan poin dari Rewards
    dashboard -> hitung vol/poin, biaya/1.000 poin, verdict G1/G3."""
    led = Ledger(cfg.db_path)
    wk = week_start_iso(datetime.now(UTC) - timedelta(days=7))   # minggu yg baru disnapshot
    vol_s = led.volume_since(wk, "S"); vol_p = led.volume_since(wk, "P")
    fees = led.fees_since(wk); e1p = led.e1_profit_since(wk)
    print(f"Minggu poin mulai {wk}")
    print(f"  Volume SPOT  : ${vol_s:,.0f}\n  Volume PERPS : ${vol_p:,.0f}")
    print(f"  Fee total    : ${fees:,.2f}\n  Profit E1    : ${e1p:,.2f}")
    try:
        pts = D(input("Poin dari dashboard utk minggu ini: ").strip())
    except Exception:
        raise SystemExit("input poin tidak valid")
    led.record_points(wk, pts, "manual")
    tot = vol_s + vol_p
    if pts > 0 and tot > 0:
        vpp = tot / pts
        net_cost = fees - e1p
        cpk = (net_cost / pts * 1000) if pts else D(0)
        print(f"  vol/poin     : ${vpp:,.0f}")
        print(f"  biaya bersih / 1.000 poin: ${cpk:,.2f}  (negatif = Anda DIBAYAR)")
        # G1: nilai konservatif $0.37/poin harus >= 3x biaya
        ok = (D('0.37') * 1000) >= 3 * max(cpk, D(0))
        print(f"  G1 verdict   : {'GO ✅' if ok else 'NO-GO ❌ — turunkan ke mode minimal'}")
        # G3: bandingkan dgn minggu sebelumnya bila ada
        prev = led.con.execute(
            "SELECT week_sat, points FROM weekly_points WHERE week_sat<? "
            "ORDER BY week_sat DESC LIMIT 1", (wk,)).fetchone()
        if prev and D(prev[1]) > 0:
            print("  G3: bandingkan vol/poin dua minggu — jika memburuk >40% dua "
                  "minggu berturut, bekukan Engine-2 (E1 tetap jalan).")
    else:
        print("  Poin 0 — periksa apakah volume terhitung / indikasi flag. WASPADA R1.")

def cmd_estimate_share(cfg: Config, path: str):
    """G5: estimasi pangsa maker 14D dari file trades collector (JSONL:
    {'ts':iso,'notional':float,'maker':bool[opsional]}). Aman: hanya baca."""
    if not os.path.isfile(path):
        raise SystemExit(f"file tidak ditemukan: {path}")
    cut = datetime.now(UTC) - timedelta(days=14)
    tot = D(0); n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                ts = datetime.fromisoformat(str(j["ts"]).replace("Z", "+00:00"))
                if ts < cut:
                    continue
                if j.get("maker", True):
                    tot += D(str(j["notional"])); n += 1
            except Exception:
                continue   # baris korup diabaikan, tidak menjatuhkan proses
    led = Ledger(cfg.db_path)
    mine = led.volume_since(cut.isoformat())
    print(f"Sampel trades platform 14D : {n:,} fill, ${tot:,.0f} (maker)")
    if tot > 0:
        # PERHATIAN ilmiah: collector Anda mungkin hanya merekam subset pair ->
        # ini ESTIMASI BAWAH utk total platform => pangsa Anda estimasi ATAS.
        share = mine / tot
        print(f"Volume maker Anda 14D      : ${mine:,.0f}")
        print(f"Pangsa (batas atas)        : {share:.3%}")
        print("G5:", "PUSH MODE — ambang rebate 0,5% terjangkau ✅" if share >= D("0.004")
              else "normal — rebate belum terjangkau")

def cmd_status(cfg: Config):
    led = Ledger(cfg.db_path)
    wk = week_start_iso()
    g = Guards(cfg, led, Telegram(cfg))
    t = Treasury(cfg, led, g)
    print(f"Minggu poin berjalan sejak {wk}")
    print(f"  Vol SPOT  : ${led.volume_since(wk,'S'):,.0f}")
    print(f"  Vol PERPS : ${led.volume_since(wk,'P'):,.0f}")
    
    fee_mgg = led.fees_since(wk)
    e1_profit = led.e1_profit_since(wk)
    print(f"  Fee mgg   : ${fee_mgg:,.2f}   Profit E1 mgg: ${e1_profit:,.2f}")

    # ── METRIK INTI MINGGUAN: E1 profit menutup E2? (doktrin user) ──
    wsum = weekly_net_summary(led)
    cov = wsum["coverage_ratio"]
    cov_str = "∞ (E2 tak rugi)" if cov is None else f"{float(cov):.2f}×"
    verdict = "✅ SEIMBANG/UNTUNG (E1 menutup E2)" if wsum["on_track"] \
              else "🔴 E1 BELUM menutup E2 (net negatif)"
    print(f"  ── Net mingguan E1+E2 (sejak Sabtu 07:00 WIB) ──")
    print(f"     E1 profit : ${float(wsum['e1_profit']):+.4f}")
    print(f"     E2 net    : ${float(wsum['e2_net']):+.4f}")
    print(f"     NET       : ${float(wsum['combined_net']):+.4f}  | coverage E1/|E2| = {cov_str}")
    print(f"     Verdict   : {verdict}")
    
    # R2: Fable KPI — SoPoints per dollar burned
    pts_row = led.con.execute("SELECT points FROM weekly_points WHERE week_sat=?", (wk,)).fetchone()
    if pts_row and float(pts_row[0]) > 0:
        pts = float(pts_row[0])
        vol_total = float(led.volume_since(wk, 'S') or 0) + float(led.volume_since(wk, 'P') or 0)
        net_cost = float(fee_mgg) - float(e1_profit)
        if net_cost > 0:
            print(f"  📊 R2 KPI: {pts:,.0f} SoPoints = ${net_cost/pts*1000:.2f} cost/1K pts | {vol_total/1000:,.0f}K vol = {pts/(vol_total/1000):,.1f} pts/1K vol")
        else:
            print(f"  📊 R2 KPI: {pts:,.0f} SoPoints = NET PROFITABLE — {vol_total/1000:,.0f}K vol = {pts/(vol_total/1000):,.1f} pts/1K vol")
    else:
        vol_total = float(led.volume_since(wk, 'S') or 0) + float(led.volume_since(wk, 'P') or 0)
        print(f"  📊 R2 KPI: SoPoints BELUM DICATAT (Selasa via 'report' cmd) — {vol_total/1000:,.0f}K vol waiting")
    
    print(f"  Fee dari pokok terpakai: ${led.get_state('principal_fee_spent'):.2f} / {cfg.principal_fee_cap}")
    print(f"  Allowance Engine-2 (G6): ${t.allowance():,.2f}")


def cmd_monitor(cfg: Config):
    """B16: Laporan Monitoring & Evaluasi berbasis DATA RIIL (on-demand).
    Membaca saldo riil exchange + ledger jujur → cetak + persist snapshot."""
    led = Ledger(cfg.db_path)
    adapter = SodexLiveAdapter(cfg)
    rep = build_monitor_report(cfg, adapter, led)
    persist_monitor_snapshot(cfg, rep)

    def _f(v, fmt="{:+.4f}", dash="—"):
        return dash if v is None else fmt.format(v)

    print("=" * 60)
    print(f"📡 MONITOR & EVALUASI TWIN-ENGINE — {rep['ts'][:19]}Z")
    print(f"   Minggu poin sejak: {rep['week_start'][:16]} (Sabtu 07:00 WIB)")
    if rep.get("degraded"):
        print(f"   ⚠️ DEGRADED: {rep.get('degraded_reason','')}")
    print("-" * 60)
    print("💰 MODAL & ASET RIIL (dari balance exchange):")
    print(f"   USDC bebas      : ${_f(rep['usdc_free'], '{:.2f}')}")
    print(f"   Nilai inventori : ${_f(rep['inventory_usd'], '{:.2f}')}")
    print(f"   EKUITAS RIIL    : ${_f(rep['real_equity'], '{:.2f}')}")
    for a in rep["assets"]:
        usd = a["usd"]
        print(f"     • {a['pair']}: {a['qty']:,.0f} qty (${usd:.2f})" if usd is not None
              else f"     • {a['pair']}: {a['qty']:,.0f} qty (harga?)")
    print("-" * 60)
    print("📈 PnL MINGGUAN (data jujur B13):")
    print(f"   E1 profit (realized): ${_f(rep['e1_profit_week'])}")
    print(f"   E2 net    (realized): ${_f(rep['e2_net_week'])}")
    print(f"   NET realized        : ${_f(rep['realized_net_week'])}")
    print(f"   PnL MtM (ekuitas Δ) : ${_f(rep['mtm_pnl_week'])}  (incl unrealized)")
    print("-" * 60)
    print("📊 VOLUME & RASIO RIIL (mingguan):")
    print(f"   Volume SPOT (E1) : ${_f(rep['vol_spot_week'], '{:,.0f}')}")
    print(f"   Volume PERPS(E2) : ${_f(rep['vol_perps_week'], '{:,.0f}')}")
    print(f"   Volume TOTAL     : ${_f(rep['vol_total_week'], '{:,.0f}')}")
    nr = rep["net_rate_week"]
    print(f"   Net rate         : {_f(nr*100, '{:+.4f}') if nr is not None else '—'}%/RT")
    wr = rep["win_rate_week"]
    print(f"   Win rate         : {_f(wr*100, '{:.1f}') if wr is not None else '—'}% "
          f"(RT: {rep['rt_count_week']} | E1={rep['rt_e1_week']} E2={rep['rt_e2_week']})")
    cov = rep["coverage_ratio"]
    print(f"   Coverage E1/|E2| : {_f(cov, '{:.2f}')+'×' if cov is not None else '∞ (E2 tak rugi)'}")
    roe = rep["return_on_equity_week"]
    print(f"   Return on equity : {_f(roe*100,'{:+.3f}') if roe is not None else '—'}%/minggu")
    print("-" * 60)
    print("🔬 KEJUJURAN DATA (apa adanya):")
    print(f"   Akunting jujur (B13) aktif sejak: {rep['b13_activated'] or 'BELUM'}")
    if rep["week_has_contaminated_data"]:
        print(f"   ⚠️ Minggu ini SEBAGIAN TERCEMAR phantom pra-B13.")
        print(f"      → Angka full-week di atas TIDAK sepenuhnya jujur.")
        print(f"   ✅ Data JUJUR saja (sejak {rep['honest_data_since'][:19]}):")
        print(f"      E1=${_f(rep['honest_e1_profit'])}  E2=${_f(rep['honest_e2_net'])}  "
              f"NET=${_f(rep['honest_net'])}")
        hnr = rep["honest_net_rate"]; hwr = rep["honest_win_rate"]
        print(f"      RT={rep['honest_rt_count']}  "
              f"net_rate={_f(hnr*100,'{:+.4f}') if hnr is not None else '—'}%  "
              f"win={_f(hwr*100,'{:.1f}') if hwr is not None else '—'}%")
    else:
        print(f"   ✅ Seluruh minggu ini = data JUJUR (post-B13).")
    print("-" * 60)
    v = rep["verdict"]
    print(f"🎯 VERDICT ({rep['verdict_basis']}): "
          f"{'✅ SEIMBANG/UNTUNG (E1 menutup E2)' if v=='SEIMBANG_ATAU_UNTUNG' else '🔴 RUGI — E1 belum menutup E2'}")
    print(f"   Snapshot disimpan: {cfg.monitor_latest}")
    print("=" * 60)


def cmd_e1research(cfg: Config):
    """B18: Riset edge E1 — distribusi spread (nol-risiko) + ekonomi RT jujur.
    Menjawab ilmiah: apakah spread cukup sering lebar agar 'quote saat spread
    lebar' layak? + berapa net rate jujur E1 saat ini."""
    fee_rt_bps = float(cfg.spot_maker_fee) * 2 * 10000
    # 1. muat sampel spread
    samples = []
    try:
        with open(cfg.spread_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        samples.append(json.loads(line))
                    except Exception:
                        continue
    except FileNotFoundError:
        print(f"⚠️ Belum ada sampel spread di {cfg.spread_path} — daemon perlu jalan dulu.")
    print("=" * 60)
    print("🔬 RISET EDGE E1 — DISTRIBUSI SPREAD (nol-risiko)")
    print(f"   Fee maker bolak-balik: {fee_rt_bps:.2f} bps")
    print("-" * 60)
    if samples:
        analysis = analyze_spread_samples(samples, fee_rt_bps)
        for pair, st in analysis["pairs"].items():
            print(f"📊 {pair} (n={st['n']} sampel):")
            print(f"   spread bps: min={st['min_bps']} median={st['median_bps']} "
                  f"p75={st['p75_bps']} p90={st['p90_bps']} max={st['max_bps']}")
            fg = st["frac_ge"]
            print(f"   fraksi waktu spread ≥ : 2×fee={fg['ge_2x_fee']:.1%} "
                  f"4×fee={fg['ge_4x_fee']:.1%} 30bps={fg['ge_30bps']:.1%} "
                  f"40bps={fg['ge_40bps']:.1%} 50bps={fg['ge_50bps']:.1%}")
    else:
        print("   (tidak ada data sampel)")
    print("-" * 60)
    # 2. ekonomi RT jujur (post-B13)
    led = Ledger(cfg.db_path)
    b13_ts = led.get_state("b13_activated_ts")
    since = (datetime.fromtimestamp(float(b13_ts), UTC).isoformat()
             if b13_ts and float(b13_ts) > 0 else None)
    for pair in ("PEPE/USDC", "SHIB/USDC"):
        rate, n = led.e1_recent_net_rate_pair(pair, n=10000, min_n=1, since_iso=since)
        if n > 0:
            print(f"📈 {pair} RT jujur: n={n} net_rate={float(rate)*100:+.4f}%/RT" if rate is not None
                  else f"📈 {pair}: n={n} (vol 0)")
        else:
            print(f"📈 {pair} RT jujur: belum ada (E1 paused/baru)")
    print("-" * 60)
    # B25: Verdict ilmiah formal (berdasarkan data aktual, bukan tebakan)
    print("🔬 VERDICT ILMIAH FORMAL:")
    if samples:
        # Tentukan apakah H1 "quote saat spread lebar" layak atau terfalsifikasi
        for pair, st in analysis["pairs"].items():
            n_s = st["n"]
            fg = st["frac_ge"]
            breakeven_bps = fee_rt_bps * 2   # spread min agar maker tidak rugi adverse
            frac_at_be = fg.get("ge_40bps", 0)  # proxy breakeven utk PEPE (~40 bps)
            if n_s < 50:
                verdict_h1 = f"⏳ DATA KURANG (n={n_s}<50) — kumpulkan lebih lama"
            elif frac_at_be == 0.0:
                verdict_h1 = (
                    f"🔴 H1 TERFALSIFIKASI — spread {pair} TIDAK PERNAH mencapai "
                    f"≥40 bps dalam {n_s} sampel (0%). 'Quote saat spread lebar' "
                    f"MUSTAHIL karena kondisi prasyarat tidak pernah terjadi."
                )
            elif frac_at_be < 0.05:
                verdict_h1 = (
                    f"🟠 H1 SANGAT LEMAH — spread {pair} ≥40 bps hanya "
                    f"{frac_at_be:.1%} waktu ({n_s} sampel). "
                    f"Volume terlalu rendah untuk edge bermakna."
                )
            else:
                verdict_h1 = (
                    f"✅ H1 LAYAK DIUJI — spread {pair} ≥40 bps sebesar "
                    f"{frac_at_be:.1%} waktu. Jalankan eksperimen B19 ber-budget."
                )
            print(f"   {verdict_h1}")
        # Verdict RT jujur (dari data B13+)
        led2 = Ledger(cfg.db_path)
        b13_ts2 = led2.get_state("b13_activated_ts")
        since2 = (datetime.fromtimestamp(float(b13_ts2), UTC).isoformat()
                  if b13_ts2 and float(b13_ts2) > 0 else None)
        all_net = []
        for pair in ("PEPE/USDC", "SHIB/USDC"):
            rate2, n2 = led2.e1_recent_net_rate_pair(pair, n=10000, min_n=1, since_iso=since2)
            if n2 >= 20 and rate2 is not None:
                all_net.append((pair, float(rate2), n2))
        if all_net:
            print(f"   📊 RT jujur (post-B13):")
            for pair2, nr, n_rt in all_net:
                rt_verdict = ("🔴 RUGI (adverse selection > spread)" if nr < -0.0003
                              else "🟡 MENDEKATI BE" if nr < 0.0001
                              else "✅ PROFIT")
                print(f"      {pair2}: n={n_rt}, net={nr*100:+.4f}%/RT → {rt_verdict}")
        print("   💡 Rekomendasi: E1 maker pasif PEPE/SHIB terfalsifikasi ilmiah.")
        print("   Prioritas → Phase 2 (E2Dir funding+OBI) sambil menunggu pair baru.")
    else:
        print("   (belum ada sampel spread — jalankan daemon lebih lama)")
    print("=" * 60)


def cmd_e1experiment(cfg: Config):
    """B19: Status & verdict EKSPERIMEN ber-budget (uji 'quote saat spread lebar').
    Menampilkan progres + decision rule pre-registered."""
    led = Ledger(cfg.db_path)
    print("=" * 60)
    print("🔬 EKSPERIMEN BER-BUDGET E1 (B19)")
    print(f"   Enabled        : {cfg.e1_research_enabled}")
    print(f"   Spread minimum : {float(cfg.e1_research_min_spread)*10000:.0f} bps")
    print(f"   Budget (maks rugi): ${float(cfg.e1_research_budget):.2f}")
    print(f"   Target sampel  : n={cfg.e1_research_target_n} RT")
    st_ts = led.get_state("e1_research_start_ts")
    if not st_ts or float(st_ts) <= 0:
        print("-" * 60)
        print("   ⏸ Eksperimen BELUM dimulai. Aktifkan: TE_E1_RESEARCH=1 di watchdog,")
        print("      lalu restart daemon. (Default OFF demi prinsip 'tidak rugi'.)")
        print("=" * 60)
        return
    since_iso = datetime.fromtimestamp(float(st_ts), UTC).isoformat()
    print(f"   Mulai          : {since_iso[:19]}")
    print("-" * 60)
    # statistik per-pair + global
    for pair in ("PEPE/USDC", "SHIB/USDC"):
        rts = led.e1_rts_since(since_iso, pair=pair)
        if rts:
            pnls = [float(p) for p, _ in rts]; vols = [float(v) for _, v in rts]
            v = experiment_verdict(pnls, vols, cfg.e1_research_target_n,
                                   float(cfg.e1_research_budget))
            print(f"📊 {pair}: n={v['n']} net_rate="
                  f"{v['net_rate']*100:+.4f}%" if v['net_rate'] is not None else f"📊 {pair}: n={v['n']}")
    # global verdict
    grts = led.e1_rts_since(since_iso)
    pnls = [float(p) for p, _ in grts]; vols = [float(v) for _, v in grts]
    v = experiment_verdict(pnls, vols, cfg.e1_research_target_n, float(cfg.e1_research_budget))
    print("-" * 60)
    print(f"📈 GLOBAL: n={v['n']}/{v['target_n']}  PnL=${v['pnl_sum']:+.4f}  "
          f"vol=${v['vol_sum']:,.0f}")
    if v["net_rate"] is not None:
        print(f"   net_rate={v['net_rate']*100:+.4f}%/RT  mean_pnl/RT=${v['mean_pnl']:+.5f}")
    if v["ci_low"] is not None:
        print(f"   95% CI mean PnL/RT: [{v['ci_low']:+.5f}, {v['ci_high']:+.5f}]")
    print(f"   Budget terpakai: ${v['budget_spent']:.2f} / ${v['budget_usd']:.2f} "
          f"(sisa ${v['budget_remaining']:.2f})")
    print(f"   Status: {v['status']}")
    print("-" * 60)
    vd = v["verdict"]
    msg = {
        "H1_SUPPORTED": "✅ H1 DIDUKUNG — E1 profit di spread lebar → set min_spread, lanjut Fase 2",
        "H1_FALSIFIED": "🔴 H1 DIFALSIFIKASI — rugi walau spread lebar → PIVOT (pair/rebate/abandon)",
        "INCONCLUSIVE": "⚠️ INCONCLUSIVE — CI melewati 0; perlu data/budget lebih",
        "INSUFFICIENT_N": f"⏳ SAMPEL KURANG (n<{30}) — eksperimen lanjut",
    }.get(vd, vd)
    print(f"🎯 VERDICT (pre-registered): {msg}")
    print("=" * 60)

def cmd_dir_status(cfg: Config):
    """Phase 2: Status Engine2Directional (funding+OBI sinyal direksional).
    Menampilkan konfigurasi, gate status, dan statistik sinyal jujur."""
    led = Ledger(cfg.db_path)
    print("=" * 60)
    print("🔀 PHASE 2 — ENGINE-2 DIREKSIONAL (E2Dir)")
    print(f"   Enabled        : {cfg.e2_dir_enabled}")
    print(f"   Pair           : {cfg.e2_dir_pair}")
    print(f"   Size per trade : ${float(cfg.e2_dir_size_usd):.2f}")
    print(f"   SL / TP        : {float(cfg.e2_dir_sl_pct)*100:.1f}% / {float(cfg.e2_dir_tp_pct)*100:.1f}%")
    print(f"   Hold maks      : {cfg.e2_dir_hold_s//60} menit")
    print(f"   Budget cap     : ${float(cfg.e2_dir_budget):.2f}")
    print(f"   Gate min-n     : {cfg.e2_dir_min_n}")
    print(f"   Funding thr    : {float(cfg.e2_dir_funding_thr)*100:.4f}%/8h")
    print(f"   OBI thr        : {float(cfg.e2_dir_obi_thr):.2f}")
    print(f"   Live enabled   : {cfg.e2_dir_live_enabled}")
    print("-" * 60)
    # Open position (B26: tampilkan dulu agar budget in-flight benar)
    op = led.e2_dir_open_signal(cfg.e2_dir_pair or None)
    inflight = float(D(str(op["entry_px"])) * D(str(op["qty"]))) if op else 0.0
    # Budget (B26: pisahkan rugi-terealisasi vs modal in-flight)
    spent = led.e2_dir_budget_spent()
    remaining = cfg.e2_dir_budget - spent
    print(f"   Budget rugi (realized) : ${float(spent):.4f}")
    if inflight > 0:
        print(f"   Modal in-flight        : ${inflight:.4f} (posisi aktif, belum closed)")
    print(f"   Budget sisa            : ${float(remaining):.4f}")
    print("-" * 60)
    # Statistik
    st = led.e2_dir_stats(cfg.e2_dir_pair)
    n = st["n"]
    if n == 0:
        print("   Sinyal tertutup: belum ada data (n=0)")
    else:
        wr = float(st["win_rate"]) * 100 if st["win_rate"] else 0
        print(f"   Sinyal tertutup: n={n}")
        print(f"   Win-rate jujur : {wr:.1f}%")
        print(f"   PnL kumulatif  : ${float(st['total_pnl']):+.4f}")
        print(f"   PnL rata-rata  : ${float(st['mean_pnl']):+.5f}/sinyal")
        # Gate decision
        min_wr = 0.40
        if n < cfg.e2_dir_min_n:
            gate = f"⏳ data kurang (n={n}<{cfg.e2_dir_min_n}) — fail-open"
        elif (st["win_rate"] or D(0)) < D(str(min_wr)):
            gate = f"🔴 HALT — WR={wr:.1f}%<{min_wr*100:.0f}% → hentikan signal baru"
        else:
            gate = f"✅ gate terbuka — WR={wr:.1f}% OK"
        print(f"   Gate WR        : {gate}")
        # B34: exit quality breakdown + binomial significance
        eq = led.e2_dir_exit_quality(cfg.e2_dir_pair or None)
        if eq:
            print("-" * 60)
            print("   Exit breakdown (B34):")
            for reason, d in sorted(eq.items()):
                wr_str = f"  WR={d['wr']*100:.0f}%" if d["wr"] is not None else ""
                print(f"     {reason:12s}: n={d['n']:3d}{wr_str}  avg={d['avg_pnl']:.5f}")
        bt = led.e2_dir_binom_test(cfg.e2_dir_pair or None)
        if bt["n"] >= 5:
            sig_label = ("★ SIGNIFIKAN p<0.05" if bt["significant_p05"]
                         else ("~ borderline p<0.10" if bt["significant_p10"]
                               else "✗ belum signifikan"))
            go_live = (bt["significant_p05"] and bt["n"] >= cfg.e2_dir_min_n
                       and (bt["wr"] or 0) >= 0.50)
            print(f"   Binomial test  : n={bt['n']} WR={bt['wr']:.0%} "
                  f"z={bt['z']:.2f} p={bt['p_val']:.3f} → {sig_label}")
            print(f"   Go-live rekomendasi: {'✅ AKTIFKAN TE_E2_DIR_LIVE=1' if go_live else '⏳ TUNGGU (n<%d atau WR<50%% atau p≥0.05)' % cfg.e2_dir_min_n}")
    if op:
        print("-" * 60)
        opened_dt = datetime.fromisoformat(op["opened_ts"].replace("Z", "+00:00"))
        age_min = (datetime.now(UTC) - opened_dt).total_seconds() / 60
        print(f"   📌 POSISI TERBUKA: {op['side'].upper()} {op['pair']} grade={op['grade']}")
        print(f"      Entry: {float(op['entry_px']):.8f}  Qty: {float(op['qty']):.6f}")
        print(f"      In-flight: ${inflight:.4f}  Usia: {age_min:.1f} mnt (timeout 30 mnt)")
        print(f"      Opened: {op['opened_ts'][:19]}")
    print("=" * 60)


def cmd_flush_pair(cfg: Config, pair: str, yes: bool):
    """B24: Jual seluruh inventory pair ke USDC (modal mati → modal aktif).

    Contoh: python3 anantara/sodex_twin_engine.py flush-pair XLM/USDC --yes

    Langkah:
      1. Cek balance coin (misal vXLM).
      2. Dapatkan orderbook — harga jual = bid (cross spread utk fast fill).
      3. Pasang limit sell di bid. Poll fill max 120 detik.
      4. Lapor hasil (USDC diperoleh setelah fee).
    SAFETY: Butuh --yes eksplisit (cegah eksekusi tidak sengaja).
    SECURITY: Tidak pernah pass private-key ke argumen CLI (dibaca dari env)."""
    if not yes:
        print("⚠️  KESELAMATAN: tambah --yes untuk konfirmasi flush (jualan nyata).")
        print(f"   Pair target: {pair}")
        print("   Jalankan: python3 anantara/sodex_twin_engine.py flush-pair "
              f"{pair} --yes")
        return

    # Derive coin name dari pair (e.g. XLM/USDC → vXLM)
    coin_raw = pair.split("/")[0] if "/" in pair else pair
    coin_vname = f"v{coin_raw}"   # SoDEX balance names (e.g. vXLM, vPEPE)

    print("=" * 60)
    print(f"🚨 FLUSH PAIR: {pair}")
    print(f"   Butuh SODEX_PRIVATE_KEY + SODEX_ACCOUNT_ID + SODEX_ADDRESS (dari env)")
    print("-" * 60)

    x = SodexLiveAdapter(cfg)

    # 1. Cek balance (simpan snapshot SEBELUM order — untuk delta detection B27)
    bals_before = x.balance()
    qty = bals_before.get(coin_vname, D(0))
    usdc_before = bals_before.get("vUSDC", D(0))
    if qty <= 0:
        print(f"   ✅ {coin_vname} sudah 0 — tidak perlu flush.")
        print("=" * 60)
        return
    print(f"   Balance {coin_vname}: {float(qty):.6f}")
    print(f"   Balance vUSDC sebelum: ${float(usdc_before):.4f}")

    # 2. Orderbook
    try:
        bk = x.book(pair)
    except Exception as e:
        print(f"   ❌ Gagal baca orderbook {pair}: {e}")
        print("=" * 60)
        return
    sell_px = D(str(bk.bid))   # normalisasi ke Decimal (defensif terhadap float mock)
    est_usd = float(qty * sell_px)
    fee_est = float(qty * sell_px * D(str(cfg.spot_maker_fee)))
    print(f"   Harga bid   : {float(sell_px):.6f}")
    print(f"   Estimasi    : ${est_usd:.4f} (sebelum fee ~${fee_est:.4f})")
    print("-" * 60)

    # 3. Pasang order SELL
    print(f"   ⏳ Memasang SELL {float(qty):.6f} {coin_raw} @ {float(sell_px):.6f}...")
    order = x.place_post_only(pair, "sell", sell_px, qty)
    if order.oid == "0":
        print(f"   ❌ Order gagal dipasang (oid='0'). Cek log untuk detail.")
        print("=" * 60)
        return
    print(f"   Order OID: {order.oid}")

    # 4. B27: Poll fill via BALANCE DELTA (bukan poll_fill).
    # Alasan: poll_fill membaca 'open orders list'. Bila order terisi LANGSUNG
    # (taker fill / matcher), order HILANG dari list sebelum sempat di-poll →
    # B9 anti-phantom mengasumsikan 'tidak terisi' dan return 0 (SALAH untuk flush).
    # Balance delta adalah sumber kebenaran: jika vXLM berkurang = terjual.
    coin_before = bals_before.get(coin_vname, D(0))
    total_filled = D(0)
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(5)
        bals_now = x.balance()
        coin_now = bals_now.get(coin_vname, D(0))
        filled_so_far = max(D(0), coin_before - coin_now)
        if filled_so_far > total_filled + D("0.001"):   # ada perubahan signifikan
            delta = filled_so_far - total_filled
            total_filled = filled_so_far
            usdc_now = bals_now.get("vUSDC", D(0))
            print(f"   ✅ +{float(delta):.4f} {coin_raw} terisi "
                  f"(kumulatif {float(total_filled):.4f}/{float(qty):.4f} | "
                  f"USDC sekarang ${float(usdc_now):.4f})")
        # Selesai bila ≥98% terisi ATAU sisa coin < 2% dari awal (dust residual)
        if total_filled >= qty * D("0.98") or coin_now <= qty * D("0.02"):
            break
    else:
        # Timeout — cancel sisa order (jika order sudah hilang/terisi, cancel diabaikan)
        print(f"   ⚠️ Timeout (120s) — terisi {float(total_filled):.4f}/{float(qty):.4f}")
        try:
            x.cancel(order)
            print(f"   Order {order.oid} dibatalkan (atau sudah tidak ada).")
        except Exception:
            pass

    # 5. Laporan final berbasis BALANCE DELTA nyata (bukan estimasi dari poll_fill)
    bals_final = x.balance()
    usdc_final = bals_final.get("vUSDC", D(0))
    usdc_recv_actual = max(D(0), usdc_final - usdc_before)
    # Fallback: bila USDC tidak berubah (akun unified), perkirakan dari filled×price
    usdc_recv_est = float(total_filled * sell_px) if total_filled > 0 else 0.0
    print("-" * 60)
    if total_filled > 0 or usdc_recv_actual > 0:
        sold_qty = float(total_filled) if total_filled > 0 else float(qty)  # approx jika delta
        usdc_display = float(usdc_recv_actual) if usdc_recv_actual > D("0.001") else usdc_recv_est
        fee_actual = sold_qty * float(sell_px) * float(cfg.spot_maker_fee)
        print(f"   ✅ FLUSH SELESAI: {sold_qty:.4f} {coin_raw} terjual")
        print(f"   USDC diterima (delta): ${float(usdc_recv_actual):.4f}")
        print(f"   USDC diterima (est)  : ${usdc_recv_est:.4f} (fee ~${fee_actual:.4f})")
        logging.info("B24/B27 flush-pair %s: sold≈%.4f px=%.6f "
                     "usdc_delta=%.4f usdc_est=%.4f",
                     pair, sold_qty, float(sell_px),
                     float(usdc_recv_actual), usdc_recv_est)
    else:
        print(f"   ❌ Tidak ada perubahan balance. Cek orderbook {pair}.")
        print(f"   (vUSDC sebelum=${float(usdc_before):.4f} sesudah=${float(usdc_final):.4f})")
    print("=" * 60)


# ============================== 10b. E1 TRIAL (B30) ==========================

def cmd_e1_trial(cfg: Config, hours: float = 1.0, cancel: bool = False):
    """B30: Manual bypass sementara B14 death spiral.

    Death spiral terjadi bila: E1 pause → tidak ada RT baru → rate beku di bawah
    floor → tidak bisa self-recover. e1-trial memungkinkan operator memberi jendela
    waktu N jam agar E1 mengumpulkan RT baru dan mengevaluasi ulang.

    Keselamatan:
    - Trial dibatasi waktu (default 1 jam). Setelah habis, gate B14 normal kembali.
    - Bila net_rate pasca-trial masih < pause_floor → auto-re-pause oleh gate B14.
    - Budget research TIDAK dipakai di sini (berbeda dari B19 yang budget-gated).
    - Trial dicatat di state DB dan terlihat di monitor/report.
    """
    led = Ledger(cfg.db_path)
    if cancel:
        led.set_state("b14_trial_until_ts", "0")
        print("✅ B30 Trial DIBATALKAN — E1 kembali ke mode B14 normal.")
        return

    trial_until = time.time() + hours * 3600
    led.set_state("b14_trial_until_ts", str(trial_until))

    # Catat RT count saat trial mulai (untuk hitung berapa RT selama trial)
    b13_ts = led.get_state("b13_activated_ts")
    since_iso = (datetime.fromtimestamp(float(b13_ts), UTC).isoformat()
                 if b13_ts and float(b13_ts) > 0 else None)
    if since_iso:
        rts = led.e1_rts_since(since_iso)
        led.set_state("b14_trial_n_at_start", str(len(rts)))
    else:
        led.set_state("b14_trial_n_at_start", "0")

    until_str = datetime.fromtimestamp(trial_until).strftime("%Y-%m-%d %H:%M:%S")
    print(f"✅ B30 E1 TRIAL AKTIF: {hours:.1f} jam sampai {until_str}")
    print(f"   E1 akan quote (meski B14 pause) untuk kumpulkan RT baru.")
    print(f"   Setelah trial: gate B14 evaluasi ulang net_rate normal.")
    print(f"   Batalkan dengan: python3 anantara/sodex_twin_engine.py e1-trial --cancel")
    print(f"   Monitor: python3 anantara/sodex_twin_engine.py monitor | python3 -m json.tool")
    print()

    # Tampilkan situasi B14 saat ini
    b14_pause_ts = led.get_state("b14_pause_since_ts")
    if float(b14_pause_ts) > 0:
        locked_h = (time.time() - float(b14_pause_ts)) / 3600
        print(f"   ⚠️  B14 saat ini AKTIF (terkunci {locked_h:.1f} jam).")
        print(f"   Rate terakhir honest: ", end="")
        rate, n = led.e1_recent_net_rate_pair(cfg.spot_pair, n=100, min_n=5, since_iso=since_iso)
        if rate is not None:
            print(f"{float(rate):.4%}/RT (n={n})")
        else:
            print("N/A (n < min)")
    else:
        print("   ℹ️  B14 saat ini TIDAK aktif (E1 sudah running).")


# ============================== 11. SELFTEST =================================

def cmd_selftest(cfg: Config):
    """Validasi ilmiah cepat di simulator: jalankan N iterasi, pastikan
    (a) ledger menulis, (b) treasury membatasi E2, (c) guard tidak jebol,
    (d) shutdown bersih. Exit code !=0 bila ada asersi gagal."""
    import tempfile
    import dataclasses
    import shutil
    print("SELFTEST: paper mode, 400 iterasi dipercepat...")
    # Use a temp DIRECTORY (not bare file): SQLite WAL mode creates db-wal &
    # db-shm siblings; rmtree on the dir removes db + wal + shm atomically with
    # no leak. mkdtemp creates atomically (no TOCTOU race like deprecated mktemp).
    tmp_dir = tempfile.mkdtemp(prefix="twin_selftest_")
    tmp_db = os.path.join(tmp_dir, "selftest.db")
    # B7: Config is a frozen dataclass — cannot assign cfg.db_path directly.
    # Use dataclasses.replace() to build a new Config with the temp DB path.
    cfg = dataclasses.replace(cfg, db_path=tmp_db)
    try:
        orch = Orchestrator(cfg, live=False)
        orch.run(max_iter=400, sleep_s=0.0)
        led = orch.led
        wk = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        fills = led.con.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        assert fills > 0, "tidak ada fill tercatat"
        e2fee = led.fees_since(wk, engine="E2")
        allow_cap = cfg.principal_fee_cap + max(D(0), led.e1_profit_since(wk))
        assert e2fee <= allow_cap + D("0.01"), f"TREASURY BREACH: E2 fee {e2fee} > cap {allow_cap}"
        inv = abs(orch.e1.inv_qty)
        print(f"  fills={fills}  E2 fee=${e2fee:.4f} (cap ${allow_cap:.2f})  inv sisa={inv:.0f} qty")
        print("  Net rate E1 (paper):", led.e1_recent_net_rate(500))
        print("SELFTEST OK ✅ — semua invarian terjaga.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ============================== 12. ENTRY POINT ==============================

def main():
    ap = argparse.ArgumentParser(description="SoDEX Twin-Engine v2 (MASTERPLAN FABLE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run");  run_p.add_argument("--live", action="store_true")
    sub.add_parser("report"); sub.add_parser("status"); sub.add_parser("selftest")
    sub.add_parser("monitor")   # B16: laporan monitoring & evaluasi data riil
    sub.add_parser("e1research")  # B18: riset edge E1 (distribusi spread)
    sub.add_parser("e1experiment")  # B19: status/verdict eksperimen ber-budget
    sub.add_parser("dir-status")    # Phase 2: status Engine2Directional
    # B30: manual bypass B14 death spiral — trial quoting untuk kumpul RT baru
    e1t = sub.add_parser("e1-trial",
                         help="B30: buka jendela trial E1 (bypass B14 pause sementara)")
    e1t.add_argument("--hours", type=float, default=1.0,
                     help="Durasi trial dalam jam (default 1.0)")
    e1t.add_argument("--cancel", action="store_true",
                     help="Batalkan trial yang sedang berjalan")
    # B24: jual inventory pair mati ke USDC (misal XLM/USDC setelah dihapus dari aktif)
    fp = sub.add_parser("flush-pair",
                        help="Jual seluruh balance pair ke USDC (butuh --yes)")
    fp.add_argument("pair", help="Pair spot, misal XLM/USDC")
    fp.add_argument("--yes", action="store_true",
                    help="Konfirmasi eksekusi (wajib; tanpa ini hanya preview)")
    est = sub.add_parser("estimate-share"); est.add_argument("trades_file")
    args = ap.parse_args()

    cfg = Config()
    setup_logging(cfg)
    check_env_file_perms()
    try:
        logging.info("integritas file SHA-256: %s", file_sha256(os.path.abspath(__file__)))
    except Exception:
        pass

    if args.cmd == "selftest":
        return cmd_selftest(cfg)
    if args.cmd == "report":
        return cmd_report(cfg)
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "monitor":
        return cmd_monitor(cfg)
    if args.cmd == "e1research":
        return cmd_e1research(cfg)
    if args.cmd == "e1experiment":
        return cmd_e1experiment(cfg)
    if args.cmd == "dir-status":
        return cmd_dir_status(cfg)
    if args.cmd == "e1-trial":
        return cmd_e1_trial(cfg, hours=args.hours, cancel=args.cancel)
    if args.cmd == "flush-pair":
        if args.yes:
            # S4 fix (audit 06-Okt-2026): flush-pair --yes menjual saldo NYATA
            # ke exchange -- sebelumnya lewati flock yg sama dgn daemon live,
            # risiko race/self-trading bila daemon live sedang jalan bersamaan.
            # WAJIB pakai lock yg sama (tanpa --yes cuma preview, aman tanpa lock).
            import fcntl
            _lock_path = "/tmp/sodex_twin_engine.lock"
            _lock_fh = open(_lock_path, "w")
            try:
                fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SystemExit(
                    f"flush-pair ditolak: engine lain (daemon live?) sedang memegang lock "
                    f"{_lock_path} — hentikan dulu atau tunggu (cegah race/self-trading).")
            _lock_fh.write(str(os.getpid())); _lock_fh.flush()
        return cmd_flush_pair(cfg, args.pair, args.yes)
    if args.cmd == "estimate-share":
        return cmd_estimate_share(cfg, args.trades_file)

    live = bool(getattr(args, "live", False))
    global MODE
    MODE = "live" if live else "dry_run"   # dicap ke ledger; bukan pengganti gate
    if live:
        # --- tiga kunci mode live ---
        if _env("CONFIRM_LIVE") != "YES":
            raise SystemExit("LIVE ditolak: set environment CONFIRM_LIVE=YES")
        if sys.stdin.isatty():
            phrase = input("Ketik persis 'SAYA PAHAM RISIKONYA' untuk lanjut LIVE: ").strip()
            if phrase != "SAYA PAHAM RISIKONYA":
                raise SystemExit("LIVE dibatalkan.")
        else:
            # S3 fix (audit 06-Okt-2026): watchdog restart otomatis SELALU non-tty
            # -> frasa konfirmasi manual TAK PERNAH jalan di produksi (watchdog_twin.sh
            # export CONFIRM_LIVE=YES setiap restart). Dulu cuma INFO log terkubur;
            # sekarang WARNING + Telegram SEKALI tiap start, supaya operator sadar
            # "3 kunci" itu efektif cuma 1 kunci (CONFIRM_LIVE) saat auto-restart.
            logging.warning("Non-interactive LIVE start — frasa konfirmasi manual DI-SKIP "
                             "(watchdog/auto-restart). CONFIRM_LIVE=YES adalah satu-satunya "
                             "gate aktif di jalur ini.")
            try:
                Telegram(cfg).send("⚠️ LIVE start non-interactive (watchdog) — frasa konfirmasi "
                                    "manual di-skip, cuma CONFIRM_LIVE env yg aktif.")
            except Exception:
                pass

    # B52: singleton flock — cegah multi-quoting bila >1 watchdog (systemd +
    # auto_evaluate nohup) men-spawn engine bersamaan. Tanpa ini, 2-3 engine
    # quote pair yang sama → inventori kacau & self-trading. Lock dipegang
    # selama proses hidup; instance kedua keluar bersih (exit 0).
    import fcntl
    _lock_path = "/tmp/sodex_twin_engine.lock"
    _lock_fh = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logging.warning("B52: engine lain sudah memegang lock %s — instance ini keluar (cegah multi-quote)", _lock_path)
        raise SystemExit(0)
    _lock_fh.write(str(os.getpid())); _lock_fh.flush()

    Orchestrator(cfg, live=live).run()

if __name__ == "__main__":
    main()
